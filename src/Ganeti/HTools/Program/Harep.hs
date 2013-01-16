{-| Auto-repair tool for Ganeti.

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

module Ganeti.HTools.Program.Harep
  ( main
  , arguments
  , options) where

import Control.Monad
import Data.Function
import Data.List
import Data.Maybe
import Data.Ord
import System.Time

import Ganeti.BasicTypes
import Ganeti.Common
import Ganeti.Types
import Ganeti.Utils
import qualified Ganeti.Constants as C
import qualified Ganeti.Path as Path

import Ganeti.HTools.CLI
import Ganeti.HTools.Loader
import Ganeti.HTools.ExtLoader
import Ganeti.HTools.Types
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Instance as Instance

-- | Options list and functions.
options :: IO [OptType]
options = do
  luxi <- oLuxiSocket
  return
    [ luxi
    ]

arguments :: [ArgCompletion]
arguments = []

data InstanceData = InstanceData { arInstance :: Instance.Instance
                                 , arState :: AutoRepairStatus
                                 , tagsToRemove :: [String]
                                 }
                    deriving (Eq, Show)

-- | Parse a tag into an 'AutoRepairData' record.
--
-- @Nothing@ is returned if the tag is not an auto-repair tag, or if it's
-- malformed.
parseInitTag :: String -> Maybe AutoRepairData
parseInitTag tag =
  let parsePending = do
        subtag <- chompPrefix C.autoRepairTagPending tag
        case sepSplit ':' subtag of
          [rtype, uuid, ts, jobs] -> makeArData rtype uuid ts jobs
          _                       -> fail ("Invalid tag: " ++ show tag)

      parseResult = do
        subtag <- chompPrefix C.autoRepairTagResult tag
        case sepSplit ':' subtag of
          [rtype, uuid, ts, result, jobs] -> do
            arData <- makeArData rtype uuid ts jobs
            result' <- autoRepairResultFromRaw result
            return arData { arResult = Just result' }
          _                               -> fail ("Invalid tag: " ++ show tag)

      makeArData rtype uuid ts jobs = do
        rtype' <- autoRepairTypeFromRaw rtype
        ts' <- tryRead "auto-repair time" ts
        jobs' <- mapM makeJobIdS $ sepSplit '+' jobs
        return AutoRepairData { arType = rtype'
                              , arUuid = uuid
                              , arTime = TOD ts' 0
                              , arJobs = jobs'
                              , arResult = Nothing
                              , arTag = tag
                              }
  in
   parsePending `mplus` parseResult

-- | Return the 'AutoRepairData' element of an 'AutoRepairStatus' type.
getArData :: AutoRepairStatus -> Maybe AutoRepairData
getArData status =
  case status of
    ArHealthy (Just d) -> Just d
    ArFailedRepair  d  -> Just d
    ArPendingRepair d  -> Just d
    ArNeedsRepair   d  -> Just d
    _                  -> Nothing

-- | Return a new list of tags to remove that includes @arTag@ if present.
delCurTag :: InstanceData -> [String]
delCurTag instData =
  let arData = getArData $ arState instData
      rmTags = tagsToRemove instData
  in
   case arData of
     Just d  -> arTag d : rmTags
     Nothing -> rmTags

-- | Set the initial auto-repair state of an instance from its auto-repair tags.
--
-- The rules when there are multiple tags is:
--
--   * the earliest failure result always wins
--
--   * two or more pending repairs results in a fatal error
--
--   * a pending result from id X and a success result from id Y result in error
--     if Y is newer than X
--
--   * if there are no pending repairs, the newest success result wins,
--     otherwise the pending result is used.
setInitialState :: Instance.Instance -> Result InstanceData
setInitialState inst =
  let arData = mapMaybe parseInitTag $ Instance.allTags inst
      -- Group all the AutoRepairData records by id (i.e. by repair task), and
      -- present them from oldest to newest.
      arData' = sortBy (comparing arUuid) arData
      arGroups = groupBy ((==) `on` arUuid) arData'
      arGroups' = sortBy (comparing $ minimum . map arTime) arGroups
  in
   foldM arStatusCmp (InstanceData inst (ArHealthy Nothing) []) arGroups'

-- | Update the initial status of an instance with new repair task tags.
--
-- This function gets called once per repair group in an instance's tag, and it
-- determines whether to set the status of the instance according to this new
-- group, or to keep the existing state. See the documentation for
-- 'setInitialState' for the rules to be followed when determining this.
arStatusCmp :: InstanceData -> [AutoRepairData] -> Result InstanceData
arStatusCmp instData arData =
  let curSt = arState instData
      arData' = sortBy (comparing keyfn) arData
      keyfn d = (arResult d, arTime d)
      newData = last arData'
      newSt = case arResult newData of
                Just ArSuccess -> ArHealthy $ Just newData
                Just ArEnoperm -> ArHealthy $ Just newData
                Just ArFailure -> ArFailedRepair newData
                Nothing        -> ArPendingRepair newData
  in
   case curSt of
     ArFailedRepair _ -> Ok instData  -- Always keep the earliest failure.
     ArHealthy _      -> Ok instData { arState = newSt
                                     , tagsToRemove = delCurTag instData
                                     }
     ArPendingRepair d -> Bad (
       "An unfinished repair was found in instance " ++
       Instance.name (arInstance instData) ++ ": found tag " ++
       show (arTag newData) ++ ", but older pending tag " ++
       show (arTag d) ++ "exists.")

     ArNeedsRepair _ -> Bad
       "programming error: ArNeedsRepair found as an initial state"

-- | Main function.
main :: Options -> [String] -> IO ()
main opts args = do
  unless (null args) $
    exitErr "this program doesn't take any arguments."

  luxiDef <- Path.defaultLuxiSocket
  let master = fromMaybe luxiDef $ optLuxi opts
      opts' = opts { optLuxi = Just master }

  (ClusterData _ _ il _ _) <- loadExternalData opts'

  let iniDataRes = mapM setInitialState $ Container.elems il
  _unused_iniData <- exitIfBad "when parsing auto-repair tags" iniDataRes

  return ()
