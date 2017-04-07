{-| Implementation of the auto-repair logic for Ganeti.

-}

{-

Copyright (C) 2013, 2015 Google Inc.
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

module Ganeti.HTools.Repair
  ( InstanceData(..)
  , parseInitTag
  , getArData
  , arStateName
  , delCurTag
  , setInitialState
  , arStatusCmp
  , updateTag
  , detectBroken
  ) where

import Control.Monad (mplus, foldM)
import Data.Function (on)
import Data.List (sortBy, groupBy, intercalate)
import Data.Maybe (mapMaybe, fromJust)
import Data.Ord (comparing)
import System.Time (ClockTime(TOD))

import Ganeti.BasicTypes (GenericResult(..), Result)
import qualified Ganeti.Constants as C
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Tags.Constants as Tags
import Ganeti.HTools.Types
import Ganeti.OpCodes (OpCode(..))
import Ganeti.OpParams ( RecreateDisksInfo(RecreateDisksAll)
                       , ReplaceDisksMode(ReplaceNewSecondary)
                       )
import Ganeti.Types (makeJobIdS, fromJobId, mkNonEmpty, mkNonNegative)
import Ganeti.Utils (chompPrefix, sepSplit, tryRead, clockTimeToString)

-- | Description of an instance annotated with repair-related information.
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
        subtag <- chompPrefix Tags.autoRepairTagPending tag
        case sepSplit ':' subtag of
          [rtype, uuid, ts, jobs] -> makeArData rtype uuid ts jobs
          _                       -> fail ("Invalid tag: " ++ show tag)

      parseResult = do
        subtag <- chompPrefix Tags.autoRepairTagResult tag
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

-- | Return a short name for each auto-repair status.
--
-- This is a more concise representation of the status, because the default
-- "Show" formatting includes all the accompanying auto-repair data.
arStateName :: AutoRepairStatus -> String
arStateName status =
  case status of
    ArHealthy _       -> "Healthy"
    ArFailedRepair _  -> "Failure"
    ArPendingRepair _ -> "Pending repair"
    ArNeedsRepair _   -> "Needs repair"

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

-- | Update the tag of an 'AutoRepairData' record to match all the other fields.
updateTag :: AutoRepairData -> AutoRepairData
updateTag arData =
  let ini = [autoRepairTypeToRaw $ arType arData,
             arUuid arData,
             clockTimeToString $ arTime arData]
      end = [intercalate "+" . map (show . fromJobId) $ arJobs arData]
      (pfx, middle) =
         case arResult arData of
          Nothing -> (Tags.autoRepairTagPending, [])
          Just rs -> (Tags.autoRepairTagResult, [autoRepairResultToRaw rs])
  in
   arData { arTag = pfx ++ intercalate ":" (ini ++ middle ++ end) }

-- | Detect brokenness with an instance and suggest repair type and jobs to run.
detectBroken :: Node.List -> Instance.Instance
             -> Maybe (AutoRepairType, [OpCode])
detectBroken nl inst =
  let disk = Instance.diskTemplate inst
      iname = Instance.name inst
      offPri = Node.offline $ Container.find (Instance.pNode inst) nl
      offSec = Node.offline $ Container.find (Instance.sNode inst) nl
  in
   case disk of
     DTDrbd8
       | offPri && offSec ->
         Just (
           ArReinstall,
           [ OpInstanceRecreateDisks { opInstanceName = iname
                                     , opInstanceUuid = Nothing
                                     , opRecreateDisksInfo = RecreateDisksAll
                                     , opNodes = []
                                       -- FIXME: there should be a better way to
                                       -- specify opcode parameters than abusing
                                       -- mkNonEmpty in this way (using the fact
                                       -- that Maybe is used both for optional
                                       -- fields, and to express failure).
                                     , opNodeUuids = Nothing
                                     , opIallocator = mkNonEmpty "hail"
                                     }
           , OpInstanceReinstall { opInstanceName = iname
                                 , opInstanceUuid = Nothing
                                 , opOsType = Nothing
                                 , opTempOsParams = Nothing
                                 , opOsparamsPrivate = Nothing
                                 , opOsparamsSecret = Nothing
                                 , opClearOsparams = False
                                 , opClearOsparamsPrivate = False
                                 , opRemoveOsparams = Nothing
                                 , opRemoveOsparamsPrivate = Nothing
                                 , opForceVariant = False
                                 }
           ])
       | offPri ->
         Just (
           ArFailover,
           [ OpInstanceFailover { opInstanceName = iname
                                , opInstanceUuid = Nothing
                                  -- FIXME: ditto, see above.
                                , opShutdownTimeout = fromJust $ mkNonNegative
                                                      C.defaultShutdownTimeout
                                , opIgnoreConsistency = False
                                , opTargetNode = Nothing
                                , opTargetNodeUuid = Nothing
                                , opIgnoreIpolicy = False
                                , opIallocator = Nothing
                                , opMigrationCleanup = False
                                }
           ])
       | offSec ->
         Just (
           ArFixStorage,
           [ OpInstanceReplaceDisks { opInstanceName = iname
                                    , opInstanceUuid = Nothing
                                    , opReplaceDisksMode = ReplaceNewSecondary
                                    , opReplaceDisksList = []
                                    , opRemoteNode = Nothing
                                      -- FIXME: ditto, see above.
                                    , opRemoteNodeUuid = Nothing
                                    , opIallocator = mkNonEmpty "hail"
                                    , opEarlyRelease = False
                                    , opIgnoreIpolicy = False
                                    }
            ])
       | otherwise -> Nothing

     DTPlain
       | offPri ->
         Just (
           ArReinstall,
           [ OpInstanceRecreateDisks { opInstanceName = iname
                                     , opInstanceUuid = Nothing
                                     , opRecreateDisksInfo = RecreateDisksAll
                                     , opNodes = []
                                       -- FIXME: ditto, see above.
                                     , opNodeUuids = Nothing
                                     , opIallocator = mkNonEmpty "hail"
                                     }
           , OpInstanceReinstall { opInstanceName = iname
                                 , opInstanceUuid = Nothing
                                 , opOsType = Nothing
                                 , opTempOsParams = Nothing
                                 , opOsparamsPrivate = Nothing
                                 , opOsparamsSecret = Nothing
                                 , opClearOsparams = False
                                 , opClearOsparamsPrivate = False
                                 , opRemoveOsparams = Nothing
                                 , opRemoveOsparamsPrivate = Nothing
                                 , opForceVariant = False
                                 }
           ])
       | otherwise -> Nothing

     _ -> Nothing  -- Other cases are unimplemented for now: DTDiskless,
                   -- DTFile, DTSharedFile, DTBlock, DTRbd, DTExt.
