{-# LANGUAGE ForeignFunctionInterface #-}
{-# OPTIONS_GHC -fno-warn-deprecated-flags #-}
-- the above is needed due to the fact that hsc2hs generates code also
-- compatible with older compilers; see
-- http://hackage.haskell.org/trac/ghc/ticket/3844

{-| Hsc2hs definitions for 'Storable' interfaces.

-}

{-

Copyright (C) 2013 Google Inc.
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

1. Redistributions of source code must retain the above copyright notice,
this list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright
notice, this list of conditions and the following disclaimer in the
documentation and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS
IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED
TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

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
