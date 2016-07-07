{-| Logical Volumes data collector.

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

module Ganeti.DataCollectors.Lv
  ( main
  , options
  , arguments
  , dcName
  , dcVersion
  , dcFormatVersion
  , dcCategory
  , dcKind
  , dcReport
  ) where


import qualified Control.Exception as E
import Control.Monad
import Data.Attoparsec.Text.Lazy as A
import Data.List
import Data.Maybe (mapMaybe)
import Data.Text.Lazy (pack, unpack)
import Network.BSD (getHostName)
import System.Process
import qualified Text.JSON as J

import qualified Ganeti.BasicTypes as BT
import Ganeti.Common
import qualified Ganeti.Constants as C
import Ganeti.Confd.ClientFunctions
import Ganeti.DataCollectors.CLI
import Ganeti.DataCollectors.Types
import Ganeti.JSON (fromJResult)
import Ganeti.Objects
import Ganeti.Storage.Lvm.LVParser
import Ganeti.Storage.Lvm.Types
import Ganeti.Utils


-- | The default setting for the maximum amount of not parsed character to
-- print in case of error.
-- It is set to use most of the screen estate on a standard 80x25 terminal.
-- TODO: add the possibility to set this with a command line parameter.
defaultCharNum :: Int
defaultCharNum = 80*20

-- | The name of this data collector.
dcName :: String
dcName = C.dataCollectorLv

-- | The version of this data collector.
dcVersion :: DCVersion
dcVersion = DCVerBuiltin

-- | The version number for the data format of this data collector.
dcFormatVersion :: Int
dcFormatVersion = 1

-- | The category of this data collector.
dcCategory :: Maybe DCCategory
dcCategory = Just DCStorage

-- | The kind of this data collector.
dcKind :: DCKind
dcKind = DCKPerf

-- | The data exported by the data collector, taken from the default location.
dcReport :: IO DCReport
dcReport = buildDCReport defaultOptions

-- * Command line options

options :: IO [OptType]
options =
  return
    [ oInputFile
    , oConfdAddr
    , oConfdPort
    , oInstances
    ]

-- | The list of arguments supported by the program.
arguments :: [ArgCompletion]
arguments = [ArgCompletion OptComplFile 0 (Just 0)]

-- | Get information about logical volumes from file (if specified) or
-- by actually running the command to get it from a live cluster.
getLvInfo :: Maybe FilePath -> IO [LVInfo]
getLvInfo inputFile = do
  let cmd = lvCommand
      params = lvParams
      fromLvs =
        ((E.try $ readProcess cmd params "") :: IO (Either IOError String)) >>=
        exitIfBad "running command" . either (BT.Bad . show) BT.Ok
  contents <-
    maybe fromLvs (\fn -> ((E.try $ readFile fn) :: IO (Either IOError String))
      >>= exitIfBad "reading from file" . either (BT.Bad . show) BT.Ok)
      inputFile
  case A.parse lvParser $ pack contents of
    A.Fail unparsedText contexts errorMessage -> exitErr $
      show (Prelude.take defaultCharNum $ unpack unparsedText) ++ "\n"
        ++ show contexts ++ "\n" ++ errorMessage
    A.Done _ lvinfoD -> return lvinfoD

-- | Get the list of real instances on the current node along with their disks,
-- either from a provided file or by querying Confd.
getInstDiskList :: Options -> IO [(RealInstanceData, [Disk])]
getInstDiskList opts = do
  instances <- maybe fromConfd fromFile $ optInstances opts
  exitIfBad "Unable to obtain the list of instances" instances
  where
    fromConfdUnchecked :: IO (BT.Result [(RealInstanceData, [Disk])])
    fromConfdUnchecked = do
      let srvAddr = optConfdAddr opts
          srvPort = optConfdPort opts
          toReal (RealInstance i, dsks) = Just (i, dsks)
          toReal _ = Nothing
      getHostName >>= \n -> BT.runResultT
                            . liftM (mapMaybe toReal)
                            $ getInstanceDisks n srvAddr srvPort

    fromConfd :: IO (BT.Result [(RealInstanceData, [Disk])])
    fromConfd =
      liftM (either (BT.Bad . show) id)
      (E.try fromConfdUnchecked ::
          IO (Either IOError (BT.Result [(RealInstanceData, [Disk])])))

    fromFile :: FilePath -> IO (BT.Result [(RealInstanceData, [Disk])])
    fromFile inputFile = do
      contents <-
        ((E.try $ readFile inputFile) :: IO (Either IOError String))
        >>= exitIfBad "reading from file" . either (BT.Bad . show) BT.Ok
      return . fromJResult "Not a list of instances" $ J.decode contents

-- | Adds the name of the instance to the information about one logical volume.
addInstNameToOneLv :: [(RealInstanceData, [Disk])] -> LVInfo -> LVInfo
addInstNameToOneLv instDiskList lvInfo =
 let lv = LogicalVolume (lviVgName lvInfo) (lviName lvInfo)
     instanceHasDisk = any (includesLogicalId lv) . snd
     rightInstance = find instanceHasDisk instDiskList
   in
     case rightInstance of
       Nothing -> lvInfo
       Just (i, _) -> lvInfo { lviInstance = Just $ realInstName i }

-- | Adds the name of the instance to the information about logical volumes.
addInstNameToLv :: [(RealInstanceData, [Disk])] -> [LVInfo] -> [LVInfo]
addInstNameToLv instDisksList = map (addInstNameToOneLv instDisksList)

-- | This function computes the JSON representation of the LV status.
buildJsonReport :: Options -> IO J.JSValue
buildJsonReport opts = do
  let inputFile = optInputFile opts
  lvInfo <- getLvInfo inputFile
  instDiskList <- getInstDiskList opts
  return . J.showJSON $ addInstNameToLv instDiskList lvInfo

-- | This function computes the DCReport for the logical volumes.
buildDCReport :: Options -> IO DCReport
buildDCReport opts =
  buildJsonReport opts >>=
    buildReport dcName dcVersion dcFormatVersion dcCategory dcKind

-- | Main function.
main :: Options -> [String] -> IO ()
main opts args = do
  unless (null args) . exitErr $ "This program takes exactly zero" ++
                                 " arguments, got '" ++ unwords args ++ "'"

  report <- buildDCReport opts
  putStrLn $ J.encode report
