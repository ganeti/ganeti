{-# LANGUAGE ForeignFunctionInterface, EmptyDataDecls #-}

{-| Ganeti-specific implementation of the Curl multi interface
(<http://curl.haxx.se/libcurl/c/libcurl-multi.html>).

TODO: Evaluate implementing and switching to
curl_multi_socket_action(3) interface, which is deemed to be more
performant for high-numbers of connections (but this is not the case
for Ganeti).

-}

{-

Copyright (C) 2013 Google Inc.

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
02110-1301, USA.

-}

module Ganeti.Curl.Multi where

import Control.Concurrent
import Control.Monad
import Data.IORef
import qualified Data.Map as Map
import Foreign.C.String
import Foreign.C.Types
import Foreign.Marshal
import Foreign.Ptr
import Foreign.Storable
import Network.Curl

import Ganeti.Curl.Internal
import Ganeti.Logging

-- * Data types

-- | Empty data type denoting a Curl multi handle. Naming is similar to
-- "Network.Curl" types.
data CurlM_

-- | Type alias for a pointer to a Curl multi handle.
type CurlMH = Ptr CurlM_

-- | Our type alias for maps indexing 'CurlH' handles to the 'IORef'
-- for the Curl code.
type HandleMap = Map.Map CurlH (IORef CurlCode)

-- * FFI declarations

foreign import ccall
  "curl_multi_init" curl_multi_init :: IO CurlMH

foreign import ccall
  "curl_multi_cleanup" curl_multi_cleanup :: CurlMH -> IO CInt

foreign import ccall
  "curl_multi_add_handle" curl_multi_add_handle :: CurlMH -> CurlH -> IO CInt

foreign import ccall
  "curl_multi_remove_handle" curl_multi_remove_handle :: CurlMH -> CurlH ->
                                                         IO CInt

foreign import ccall
  "curl_multi_perform" curl_multi_perform :: CurlMH -> Ptr CInt -> IO CInt

foreign import ccall
  "curl_multi_info_read" curl_multi_info_read :: CurlMH -> Ptr CInt
                                              -> IO (Ptr CurlMsg)

-- * Wrappers over FFI functions

-- | Adds an easy handle to a multi handle. This is a nicer wrapper
-- over 'curl_multi_add_handle' that fails for wrong codes.
curlMultiAddHandle :: CurlMH -> Curl -> IO ()
curlMultiAddHandle multi easy = do
  r <- curlPrim easy $ \_ x -> curl_multi_add_handle multi x
  when (toMCode r /= CurlmOK) .
    fail $ "Failed adding easy handle to multi handle: " ++ show r

-- | Nice wrapper over 'curl_multi_info_read' that massages the
-- results into Haskell types.
curlMultiInfoRead :: CurlMH -> IO (Maybe CurlMsg, CInt)
curlMultiInfoRead multi =
  alloca $ \ppending -> do
    pmsg <- curl_multi_info_read multi ppending
    pending <- peek ppending
    msg <- if pmsg == nullPtr
             then return Nothing
             else Just `fmap` peek pmsg
    return (msg, pending)

-- | Nice wrapper over 'curl_multi_perform'.
curlMultiPerform :: CurlMH -> IO (CurlMCode, CInt)
curlMultiPerform multi =
  alloca $ \running -> do
    mcode <- curl_multi_perform multi running
    running' <- peek running
    return (toMCode mcode, running')

-- * Helper functions

-- | Magical constant for the polling delay. This needs to be chosen such that:
--
-- * we don't poll too often; a slower poll allows the RTS to schedule
--   other threads, and let them work
--
-- * we don't want to pool too slow, so that Curl gets to act on the
--   handles that need it
pollDelayInterval :: Int
pollDelayInterval = 10000

-- | Writes incoming curl data to a list of strings, stored in an 'IORef'.
writeHandle :: IORef [String] -> Ptr CChar -> CInt -> CInt -> Ptr () -> IO CInt
writeHandle bufref cstr sz nelems _ = do
  let full_sz = sz * nelems
  hs_str <- peekCStringLen (cstr, fromIntegral full_sz)
  modifyIORef bufref (hs_str:)
  return full_sz

-- | Loops and extracts all pending messages from a Curl multi handle.
readMessages :: CurlMH -> HandleMap -> IO ()
readMessages mh hmap = do
  (cmsg, pending) <- curlMultiInfoRead mh
  case cmsg of
    Nothing -> return ()
    Just (CurlMsg msg eh res) -> do
      logDebug $ "Got msg! msg " ++ show msg ++ " res " ++ show res ++
               ", " ++ show pending ++ " messages left"
      let cref = (Map.!) hmap eh
      writeIORef cref res
      _ <- curl_multi_remove_handle mh eh
      when (pending > 0) $ readMessages mh hmap

-- | Loops and polls curl until there are no more remaining handles.
performMulti :: CurlMH -> HandleMap -> CInt -> IO ()
performMulti mh hmap expected = do
  (mcode, running) <- curlMultiPerform mh
  delay <- case mcode of
             CurlmCallMultiPerform -> return $ return ()
             CurlmOK -> return $ threadDelay pollDelayInterval
             code -> error $ "Received bad return code from" ++
                     "'curl_multi_perform': " ++ show code
  logDebug $ "mcode: " ++ show mcode ++ ", remaining: " ++ show running
  -- check if any handles are done and then retrieve their messages
  when (expected /= running) $ readMessages mh hmap
  -- and if we still have handles running, loop
  when (running > 0) $ delay >> performMulti mh hmap running

-- | Template for the Curl error buffer.
errorBuffer :: String
errorBuffer = replicate errorBufferSize '\0'

-- | Allocate a NULL-initialised error buffer.
mallocErrorBuffer :: IO CString
mallocErrorBuffer = fst `fmap` newCStringLen errorBuffer

-- | Initialise a curl handle. This is just a wrapper over the
-- "Network.Curl" function 'initialize', plus adding our options.
makeEasyHandle :: (IORef [String], Ptr CChar, ([CurlOption], URLString))
               -> IO Curl
makeEasyHandle (f, e, (opts, url)) = do
  h <- initialize
  setopts h opts
  setopts h [ CurlWriteFunction (writeHandle f)
            , CurlErrorBuffer e
            , CurlURL url
            , CurlFailOnError True
            , CurlNoSignal True
            , CurlProxy ""
            ]
  return h

-- * Main multi-call work function

-- | Perform a multi-call against a list of nodes.
execMultiCall :: [([CurlOption], String)] -> IO [(CurlCode, String)]
execMultiCall ous = do
  -- error buffers
  errorbufs <- mapM (\_ -> mallocErrorBuffer) ous
  -- result buffers
  outbufs <- mapM (\_ -> newIORef []) ous
  -- handles
  ehandles <- mapM makeEasyHandle $ zip3 outbufs errorbufs ous
  -- data.map holding handles to error code iorefs
  hmap <- foldM (\m h -> curlPrim h (\_ hnd -> do
                                       ccode <- newIORef CurlOK
                                       return $ Map.insert hnd ccode m
                                    )) Map.empty ehandles
  mh <- curl_multi_init
  mapM_ (curlMultiAddHandle mh) ehandles
  performMulti mh hmap (fromIntegral $ length ehandles)
  -- dummy code to keep the handles alive until here
  mapM_ (\h -> curlPrim h (\_ _ -> return ())) ehandles
  -- cleanup the multi handle
  mh_cleanup <- toMCode `fmap` curl_multi_cleanup mh
  when (mh_cleanup /= CurlmOK) .
    logError $ "Non-OK return from multi_cleanup: " ++ show mh_cleanup
  -- and now extract the data from the IORefs
  mapM (\(e, b, h) -> do
          s <- peekCString e
          free e
          cref <- curlPrim h (\_ hnd -> return $ (Map.!) hmap hnd)
          ccode <- readIORef cref
          result <- if ccode == CurlOK
                      then (concat . reverse) `fmap` readIORef b
                      else return s
          return (ccode, result)
       ) $ zip3 errorbufs outbufs ehandles
