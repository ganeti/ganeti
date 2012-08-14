{-| Implementation of the Ganeti configuration database.

-}

{-

Copyright (C) 2011, 2012 Google Inc.

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

module Ganeti.Config
    ( LinkIpMap
    , loadConfig
    , getNodeInstances
    , getDefaultNicLink
    , getInstancesIpByLink
    , getNode
    , getInstance
    , getInstPrimaryNode
    , getInstMinorsForNode
    , buildLinkIpInstnameMap
    , instNodes
    ) where

import Data.List (foldl')
import qualified Data.Map as M
import qualified Data.Set as S
import qualified Text.JSON as J

import Ganeti.HTools.JSON
import Ganeti.BasicTypes

import qualified Ganeti.Constants as C
import Ganeti.Objects

-- | Type alias for the link and ip map.
type LinkIpMap = M.Map String (M.Map String String)

-- | Reads the config file.
readConfig :: FilePath -> IO String
readConfig = readFile

-- | Parses the configuration file.
parseConfig :: String -> Result ConfigData
parseConfig = fromJResult "parsing configuration" . J.decodeStrict

-- | Wrapper over 'readConfig' and 'parseConfig'.
loadConfig :: FilePath -> IO (Result ConfigData)
loadConfig = fmap parseConfig . readConfig

-- * Query functions

-- | Computes the nodes covered by a disk.
computeDiskNodes :: Disk -> S.Set String
computeDiskNodes dsk =
  case diskLogicalId dsk of
    LIDDrbd8 nodeA nodeB _ _ _ _ -> S.fromList [nodeA, nodeB]
    _ -> S.empty

-- | Computes all disk-related nodes of an instance. For non-DRBD,
-- this will be empty, for DRBD it will contain both the primary and
-- the secondaries.
instDiskNodes :: Instance -> S.Set String
instDiskNodes = S.unions . map computeDiskNodes . instDisks

-- | Computes all nodes of an instance.
instNodes :: Instance -> S.Set String
instNodes inst = instPrimaryNode inst `S.insert` instDiskNodes inst

-- | Computes the secondary nodes of an instance. Since this is valid
-- only for DRBD, we call directly 'instDiskNodes', skipping over the
-- extra primary insert.
instSecondaryNodes :: Instance -> S.Set String
instSecondaryNodes inst =
  instPrimaryNode inst `S.delete` instDiskNodes inst

-- | Get instances of a given node.
getNodeInstances :: ConfigData -> String -> ([Instance], [Instance])
getNodeInstances cfg nname =
    let all_inst = M.elems . fromContainer . configInstances $ cfg
        pri_inst = filter ((== nname) . instPrimaryNode) all_inst
        sec_inst = filter ((nname `S.member`) . instSecondaryNodes) all_inst
    in (pri_inst, sec_inst)

-- | Returns the default cluster link.
getDefaultNicLink :: ConfigData -> String
getDefaultNicLink =
  nicpLink . (M.! C.ppDefault) . fromContainer .
  clusterNicparams . configCluster

-- | Returns instances of a given link.
getInstancesIpByLink :: LinkIpMap -> String -> [String]
getInstancesIpByLink linkipmap link =
  M.keys $ M.findWithDefault M.empty link linkipmap

-- | Generic lookup function that converts from a possible abbreviated
-- name to a full name.
getItem :: String -> String -> M.Map String a -> Result a
getItem kind name allitems = do
  let lresult = lookupName (M.keys allitems) name
      err = \details -> Bad $ kind ++ " name " ++ name ++ " " ++ details
  fullname <- case lrMatchPriority lresult of
                PartialMatch -> Ok $ lrContent lresult
                ExactMatch -> Ok $ lrContent lresult
                MultipleMatch -> err "has multiple matches"
                FailMatch -> err "not found"
  maybe (err "not found after successfull match?!") Ok $
        M.lookup fullname allitems

-- | Looks up a node.
getNode :: ConfigData -> String -> Result Node
getNode cfg name = getItem "Node" name (fromContainer $ configNodes cfg)

-- | Looks up an instance.
getInstance :: ConfigData -> String -> Result Instance
getInstance cfg name =
  getItem "Instance" name (fromContainer $ configInstances cfg)

-- | Looks up an instance's primary node.
getInstPrimaryNode :: ConfigData -> String -> Result Node
getInstPrimaryNode cfg name =
  getInstance cfg name >>= return . instPrimaryNode >>= getNode cfg

-- | Filters DRBD minors for a given node.
getDrbdMinorsForNode :: String -> Disk -> [(Int, String)]
getDrbdMinorsForNode node disk =
  let child_minors = concatMap (getDrbdMinorsForNode node) (diskChildren disk)
      this_minors =
        case diskLogicalId disk of
          LIDDrbd8 nodeA nodeB _ minorA minorB _
            | nodeA == node -> [(minorA, nodeB)]
            | nodeB == node -> [(minorB, nodeA)]
          _ -> []
  in this_minors ++ child_minors

-- | String for primary role.
rolePrimary :: String
rolePrimary = "primary"

-- | String for secondary role.
roleSecondary :: String
roleSecondary = "secondary"

-- | Gets the list of DRBD minors for an instance that are related to
-- a given node.
getInstMinorsForNode :: String -> Instance
                     -> [(String, Int, String, String, String, String)]
getInstMinorsForNode node inst =
  let role = if node == instPrimaryNode inst
               then rolePrimary
               else roleSecondary
      iname = instName inst
  -- FIXME: the disk/ build there is hack-ish; unify this in a
  -- separate place, or reuse the iv_name (but that is deprecated on
  -- the Python side)
  in concatMap (\(idx, dsk) ->
            [(node, minor, iname, "disk/" ++ show idx, role, peer)
               | (minor, peer) <- getDrbdMinorsForNode node dsk]) .
     zip [(0::Int)..] . instDisks $ inst

-- | Builds link -> ip -> instname map.
--
-- TODO: improve this by splitting it into multiple independent functions:
--
-- * abstract the \"fetch instance with filled params\" functionality
--
-- * abstsract the [instance] -> [(nic, instance_name)] part
--
-- * etc.
buildLinkIpInstnameMap :: ConfigData -> LinkIpMap
buildLinkIpInstnameMap cfg =
  let cluster = configCluster cfg
      instances = M.elems . fromContainer . configInstances $ cfg
      defparams = (M.!) (fromContainer $ clusterNicparams cluster) C.ppDefault
      nics = concatMap (\i -> [(instName i, nic) | nic <- instNics i])
             instances
  in foldl' (\accum (iname, nic) ->
               let pparams = nicNicparams nic
                   fparams = fillNICParams defparams pparams
                   link = nicpLink fparams
               in case nicIp nic of
                    Nothing -> accum
                    Just ip -> let oldipmap = M.findWithDefault (M.empty)
                                              link accum
                                   newipmap = M.insert ip iname oldipmap
                               in M.insert link newipmap accum
            ) M.empty nics
