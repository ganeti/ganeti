{-| Utility functions for cluster operations

-}

{-

Copyright (C) 2009, 2010, 2011, 2012, 2013 Google Inc.
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

module Ganeti.HTools.Cluster.Utils
  ( splitCluster
  , iMoveToJob
  , instancePriGroup
  , availableGroupNodes
  ) where

import Data.Maybe (fromJust)
import qualified Data.IntSet as IntSet

import Ganeti.BasicTypes
import qualified Ganeti.Constants as C
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.Node as Node
import Ganeti.HTools.Types
import qualified Ganeti.OpCodes as OpCodes
import Ganeti.Types (mkNonEmpty, mkNonNegative)

-- | Splits a cluster into the component node groups.
splitCluster :: Node.List -> Instance.List ->
                [(Gdx, (Node.List, Instance.List))]
splitCluster nl il =
  let ngroups = Node.computeGroups (Container.elems nl)
  in map (\(gdx, nodes) ->
           let nidxs = map Node.idx nodes
               nodes' = zip nidxs nodes
               instances = Container.filter ((`elem` nidxs) . Instance.pNode) il
           in (gdx, (Container.fromList nodes', instances))) ngroups

-- | Convert a placement into a list of OpCodes (basically a job).
iMoveToJob :: Node.List        -- ^ The node list; only used for node
                               -- names, so any version is good
                               -- (before or after the operation)
           -> Instance.List    -- ^ The instance list; also used for
                               -- names only
           -> Idx              -- ^ The index of the instance being
                               -- moved
           -> IMove            -- ^ The actual move to be described
           -> [OpCodes.OpCode] -- ^ The list of opcodes equivalent to
                               -- the given move
iMoveToJob nl il idx move =
  let inst = Container.find idx il
      iname = Instance.name inst
      lookNode  n = case mkNonEmpty (Container.nameOf nl n) of
                      -- FIXME: convert htools codebase to non-empty strings
                      Bad msg -> error $ "Empty node name for idx " ++
                                 show n ++ ": " ++ msg ++ "??"
                      Ok ne -> Just ne
      opF' = OpCodes.OpInstanceMigrate
              { OpCodes.opInstanceName        = iname
              , OpCodes.opInstanceUuid        = Nothing
              , OpCodes.opMigrationMode       = Nothing -- default
              , OpCodes.opOldLiveMode         = Nothing -- default as well
              , OpCodes.opTargetNode          = Nothing -- this is drbd
              , OpCodes.opTargetNodeUuid      = Nothing
              , OpCodes.opAllowRuntimeChanges = False
              , OpCodes.opIgnoreIpolicy       = False
              , OpCodes.opMigrationCleanup    = False
              , OpCodes.opIallocator          = Nothing
              , OpCodes.opAllowFailover       = True
              , OpCodes.opIgnoreHvversions    = True
              }
      opFA n = opF { OpCodes.opTargetNode = lookNode n } -- not drbd
      opFforced =
        OpCodes.OpInstanceFailover
          { OpCodes.opInstanceName        = iname
          , OpCodes.opInstanceUuid        = Nothing
          , OpCodes.opShutdownTimeout     =
              fromJust $ mkNonNegative C.defaultShutdownTimeout
          , OpCodes.opIgnoreConsistency = False
          , OpCodes.opTargetNode = Nothing
          , OpCodes.opTargetNodeUuid = Nothing
          , OpCodes.opIgnoreIpolicy = False
          , OpCodes.opIallocator = Nothing
          , OpCodes.opMigrationCleanup = False
          }
      opF = if Instance.forthcoming inst then opFforced else opF'
      opR n = OpCodes.OpInstanceReplaceDisks
                { OpCodes.opInstanceName     = iname
                , OpCodes.opInstanceUuid     = Nothing
                , OpCodes.opEarlyRelease     = False
                , OpCodes.opIgnoreIpolicy    = False
                , OpCodes.opReplaceDisksMode = OpCodes.ReplaceNewSecondary
                , OpCodes.opReplaceDisksList = []
                , OpCodes.opRemoteNode       = lookNode n
                , OpCodes.opRemoteNodeUuid   = Nothing
                , OpCodes.opIallocator       = Nothing
                }
  in case move of
       Failover -> [ opF ]
       FailoverToAny np -> [ opFA np ]
       ReplacePrimary np -> [ opF, opR np, opF ]
       ReplaceSecondary ns -> [ opR ns ]
       ReplaceAndFailover np -> [ opR np, opF ]
       FailoverAndReplace ns -> [ opF, opR ns ]

-- | Computes the group of an instance per the primary node.
instancePriGroup :: Node.List -> Instance.Instance -> Gdx
instancePriGroup nl i =
  let pnode = Container.find (Instance.pNode i) nl
  in  Node.group pnode

-- | Computes the nodes in a given group which are available for
-- allocation.
availableGroupNodes :: [(Gdx, [Ndx])] -- ^ Group index/node index assoc list
                    -> IntSet.IntSet  -- ^ Nodes that are excluded
                    -> Gdx            -- ^ The group for which we
                                      -- query the nodes
                    -> Result [Ndx]   -- ^ List of available node indices
availableGroupNodes group_nodes excl_ndx gdx = do
  local_nodes <- maybe (Bad $ "Can't find group with index " ++ show gdx)
                 Ok (lookup gdx group_nodes)
  let avail_nodes = filter (not . flip IntSet.member excl_ndx) local_nodes
  return avail_nodes

