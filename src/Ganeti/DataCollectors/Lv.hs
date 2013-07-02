{-| Logical Volumes data collector.

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
import Data.Text.Lazy (pack, unpack)
import Network.BSD (getHostName)
import System.Process
import qualified Text.JSON as J

import qualified Ganeti.BasicTypes as BT
import Ganeti.Common
import Ganeti.Confd.ClientFunctions
import Ganeti.DataCollectors.CLI
import Ganeti.DataCollectors.Types
import Ganeti.JSON
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
dcName = "lv"

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

-- | Get the list of instances on the current node (both primary and secondary)
-- either from a provided file or by querying Confd.
getInstanceList :: Options -> IO ([Instance], [Instance])
getInstanceList opts = do
  let srvAddr = optConfdAddr opts
      srvPort = optConfdPort opts
      instFile = optInstances opts
      fromConfdUnchecked :: IO (BT.Result ([Instance], [Instance]))
      fromConfdUnchecked = getHostName >>= \n -> getInstances n srvAddr srvPort
      fromConfd :: IO (BT.Result ([Instance], [Instance]))
      fromConfd =
        liftM (either (BT.Bad . show) id) (E.try fromConfdUnchecked :: 
          IO (Either IOError (BT.Result ([Instance], [Instance]))))
      fromFile :: FilePath -> IO (BT.Result ([Instance], [Instance]))
      fromFile inputFile = do
        contents <-
          ((E.try $ readFile inputFile) :: IO (Either IOError String))
            >>= exitIfBad "reading from file" . either (BT.Bad . show) BT.Ok
        return . fromJResult "Not a list of instances" $ J.decode contents
  instances <- maybe fromConfd fromFile instFile
  exitIfBad "Unable to obtain the list of instances" instances

-- | Adds the name of the instance to the information about one logical volume.
addInstNameToOneLv :: [Instance] -> LVInfo -> LVInfo
addInstNameToOneLv instances lvInfo =
  let vg_name = lviVgName lvInfo
      lv_name = lviName lvInfo
      instanceHasDisk = any (includesLogicalId vg_name lv_name) . instDisks
      rightInstance = find instanceHasDisk instances
    in 
      case rightInstance of
        Nothing -> lvInfo
        Just i -> lvInfo { lviInstance = Just $ instName i }

-- | Adds the name of the instance to the information about logical volumes.
addInstNameToLv :: [Instance] -> [LVInfo] -> [LVInfo]
addInstNameToLv instances = map (addInstNameToOneLv instances)

-- | This function computes the JSON representation of the LV status.
buildJsonReport :: Options -> IO J.JSValue
buildJsonReport opts = do
  let inputFile = optInputFile opts
  lvInfo <- getLvInfo inputFile
  (prim, sec) <- getInstanceList opts
  return . J.showJSON $ addInstNameToLv (prim ++ sec) lvInfo

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
