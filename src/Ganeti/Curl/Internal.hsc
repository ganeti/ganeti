{-# LANGUAGE ForeignFunctionInterface #-}
{-# OPTIONS_GHC -fno-warn-deprecated-flags #-}
-- the above is needed due to the fact that hsc2hs generates code also
-- compatible with older compilers; see
-- http://hackage.haskell.org/trac/ghc/ticket/3844

{-| Hsc2hs definitions for 'Storable' interfaces.

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

module Ganeti.Curl.Internal
  ( CurlMsgCode(..)
  , toMsgCode
  , fromMsgCode
  , CurlMsg(..)
  , errorBufferSize
  , CurlMCode(..)
  , toMCode
  ) where

import Foreign
import Foreign.C.Types

import Network.Curl

#include <curl/curl.h>

-- | Data representing a @CURLMSG@ enum.
data CurlMsgCode = CurlMsgNone
                 | CurlMsgDone
                 | CurlMsgUnknown CInt -- ^ Haskell specific code for
                                       -- unknown codes
                   deriving (Show, Eq)

-- | Data representing a @struct CURLMsg@.
data CurlMsg = CurlMsg
  { cmMessage :: CurlMsgCode -- ^ The message type
  , cmHandle  :: CurlH       -- ^ The internal curl handle to which it applies
  , cmResult  :: CurlCode    -- ^ The message-specific result
  }

-- | Partial 'Storable' instance for 'CurlMsg'; we do not extract all
-- fields, only the one we are interested in.
instance Storable CurlMsg where
  sizeOf    _ = (#size CURLMsg)
  alignment _ = alignment (undefined :: CInt)
  peek ptr = do
    msg <- (#peek CURLMsg, msg) ptr
    handle <- (#peek CURLMsg, easy_handle) ptr
    result <- (#peek CURLMsg, data.result) ptr
    return $ CurlMsg (toMsgCode msg) handle (toCode result)
  poke ptr (CurlMsg msg handle result) = do
    (#poke CURLMsg, msg) ptr (fromMsgCode msg)
    (#poke CURLMsg, easy_handle) ptr handle
    (#poke CURLMsg, data.result) ptr ((fromIntegral $ fromEnum result)::CInt)

-- | Minimum buffer size for 'CurlErrorBuffer'.
errorBufferSize :: Int
errorBufferSize = (#const CURL_ERROR_SIZE)

-- | Multi interface error codes.
data CurlMCode = CurlmCallMultiPerform
               | CurlmOK
               | CurlmBadHandle
               | CurlmBadEasyHandle
               | CurlmOutOfMemory
               | CurlmInternalError
               | CurlmBadSocket
               | CurlmUnknownOption
               | CurlmUnknown CInt -- ^ Haskell specific code denoting
                                   -- undefined codes (e.g. when
                                   -- libcurl has defined new codes
                                   -- that are not implemented yet)
                 deriving (Show, Eq)

-- | Convert a CInt CURLMSG code (as returned by the C library) to a
-- 'CurlMsgCode'. When an unknown code is received, the special
-- 'CurlMsgUnknown' constructor will be used.
toMsgCode :: CInt -> CurlMsgCode
toMsgCode (#const CURLMSG_NONE) = CurlMsgNone
toMsgCode (#const CURLMSG_DONE) = CurlMsgDone
toMsgCode v = CurlMsgUnknown v

-- | Convert a CurlMsgCode to a CInt.
fromMsgCode :: CurlMsgCode -> CInt
fromMsgCode CurlMsgNone = (#const CURLMSG_NONE)
fromMsgCode CurlMsgDone = (#const CURLMSG_DONE)
fromMsgCode (CurlMsgUnknown v) = v

-- | Convert a CInt CURLMcode (as returned by the C library) to a
-- 'CurlMCode'. When an unknown code is received, the special
-- 'CurlmUnknown' constructor will be used.
toMCode :: CInt -> CurlMCode
toMCode (#const CURLM_CALL_MULTI_PERFORM) = CurlmCallMultiPerform
toMCode (#const CURLM_OK)                 = CurlmOK
toMCode (#const CURLM_BAD_HANDLE)         = CurlmBadHandle
toMCode (#const CURLM_BAD_EASY_HANDLE)    = CurlmBadEasyHandle
toMCode (#const CURLM_OUT_OF_MEMORY)      = CurlmOutOfMemory
toMCode (#const CURLM_INTERNAL_ERROR)     = CurlmInternalError
toMCode (#const CURLM_BAD_SOCKET)         = CurlmBadSocket
toMCode (#const CURLM_UNKNOWN_OPTION)     = CurlmUnknownOption
toMCode v = CurlmUnknown v
