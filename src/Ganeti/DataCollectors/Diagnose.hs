{-| Self-diagnose data collector

-}

{-

Copyright (C) 2015 Google Inc.
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

module Ganeti.DataCollectors.Diagnose
  ( dcName
  , dcCategory
  , dcKind
  , dcReport
  ) where

import Control.Monad.Trans.Class (lift)
import System.Directory (doesFileExist)
import System.FilePath.Posix (isValid, takeFileName, (</>))
import System.Posix.Files ( getFileStatus
                          , fileOwner
                          , fileGroup
                          , fileMode
                          , ownerModes
                          , groupReadMode
                          , groupExecuteMode
                          , otherReadMode
                          , otherExecuteMode
                          , intersectFileModes
                          , unionFileModes
                          , ownerExecuteMode
                          , isRegularFile
                          , regularFileMode
                          )
import System.Process (readProcess)
import Text.JSON (JSValue(..), toJSObject, toJSString, decode, Result(..))

import Ganeti.BasicTypes (runResultT, ResultT(..), genericResult)
import Ganeti.Confd.ClientFunctions (getDiagnoseCollectorFilename)
import Ganeti.Constants (dataCollectorDiagnose, dataCollectorDiagnoseDirectory)
import Ganeti.DataCollectors.Types ( DCCategory(..)
                                   , DCKind(..)
                                   , DCVersion(..)
                                   , DCReport(..)
                                   , buildReport
                                   )

-- | The name of this data collector.
dcName :: String
dcName = dataCollectorDiagnose

-- | The category of this data collector.
dcCategory :: Maybe DCCategory
dcCategory = Just DCNode

-- | The kind of this data collector.
dcKind :: DCKind
dcKind = DCKStatus

-- | The version of this data collector.
dcVersion :: DCVersion
dcVersion = DCVerBuiltin

-- | The version number for the data format of this data collector.
dcFormatVersion :: Int
dcFormatVersion = 1

okWithDetails :: String -> JSValue
okWithDetails details = JSObject $ toJSObject
  [ ("status", JSString $ toJSString "Ok")
  , ("details", JSString $ toJSString details)
  ]


fnToVal :: String -> IO JSValue
fnToVal fn
  | null fn = return $ okWithDetails
      "No file specified for diagnose data collector"
  | not $ isValid fn = return $ okWithDetails
      "Invalid filename specified for diagnose data collector"
  | takeFileName fn /= fn = return $ okWithDetails
      "Filepaths cannot be specified for diagnose data collector"
  | otherwise = do
      let fp = dataCollectorDiagnoseDirectory </> fn
      exists <- doesFileExist fp
      if exists
        then do
          fs <- getFileStatus fp
          let maxFileMode = foldl1 unionFileModes [ ownerModes
                                                  , groupReadMode
                                                  , groupExecuteMode
                                                  , otherReadMode
                                                  , otherExecuteMode
                                                  , regularFileMode
                                                  ]
              isSubSetOf m1 m2 = m1 `intersectFileModes` m2 == m1
          case () of _
                       | fileOwner fs /= 0 -> return . okWithDetails $
                         "File for diagnose data collector " ++
                         "must be owned by root"
                       | fileGroup fs /= 0 -> return . okWithDetails $
                         "File for diagnose data collector " ++
                         "must have group root"
                       | not $ isRegularFile fs -> return . okWithDetails $
                         "File for diagnose data collector " ++
                         "must be a regular file"
                       | not $ isSubSetOf (fileMode fs) maxFileMode ->
                         return . okWithDetails $
                           "File for diagnose data collector " ++
                           "must have permissions 755 or stricter"
                       | not $ isSubSetOf ownerExecuteMode (fileMode fs) ->
                         return . okWithDetails $
                           "File for diagnose data collector " ++
                           "must be executable by owner"
                       | otherwise -> do
                         r <- fmap decode (readProcess fp [] "")
                         case r of
                           Ok val -> return val
                           Error str -> return . okWithDetails $
                             "Could not parse result: " ++ str
        else return $ okWithDetails
          "File specified for diagnose data collector does not exist"

buildJsonReport :: IO JSValue
buildJsonReport = fmap (genericResult okWithDetails id) . runResultT $ do
  statusFnName <- getDiagnoseCollectorFilename Nothing Nothing
  lift $ fnToVal statusFnName

-- | The data exported by the data collector, taken from the default location.
dcReport :: IO DCReport
dcReport = buildJsonReport >>=
  buildReport dcName dcVersion dcFormatVersion dcCategory dcKind
