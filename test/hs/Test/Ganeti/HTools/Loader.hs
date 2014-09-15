{-# LANGUAGE TemplateHaskell #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Unittests for ganeti-htools.

-}

{-

Copyright (C) 2009, 2010, 2011, 2012 Google Inc.
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

module Test.Ganeti.HTools.Loader (testHTools_Loader) where

import Test.QuickCheck

import qualified Data.IntMap as IntMap
import qualified Data.Map as Map
import Data.List
import System.Time (ClockTime(..))

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon
import Test.Ganeti.HTools.Node ()

import qualified Ganeti.BasicTypes as BasicTypes
import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Loader as Loader
import qualified Ganeti.HTools.Node as Node

prop_lookupNode :: [(String, Int)] -> String -> String -> Property
prop_lookupNode ktn inst node =
  Loader.lookupNode nl inst node ==? Map.lookup node nl
    where nl = Map.fromList ktn

prop_lookupInstance :: [(String, Int)] -> String -> Property
prop_lookupInstance kti inst =
  Loader.lookupInstance il inst ==? Map.lookup inst il
    where il = Map.fromList kti

prop_assignIndices :: Property
prop_assignIndices =
  -- generate nodes with unique names
  forAll (arbitrary `suchThat`
          (\nodes ->
             let names = map Node.name nodes
             in length names == length (nub names))) $ \nodes ->
  let (nassoc, kt) =
        Loader.assignIndices (map (\n -> (Node.name n, n)) nodes)
  in Map.size nassoc == length nodes &&
     Container.size kt == length nodes &&
     (null nodes || maximum (IntMap.keys kt) == length nodes - 1)

-- | Checks that the number of primary instances recorded on the nodes
-- is zero.
prop_mergeData :: [Node.Node] -> Bool
prop_mergeData ns =
  let na = Container.fromList $ map (\n -> (Node.idx n, n)) ns
  in case Loader.mergeData [] [] [] [] (TOD 0 0)
         (Loader.emptyCluster {Loader.cdNodes = na}) of
    BasicTypes.Bad _ -> False
    BasicTypes.Ok (Loader.ClusterData _ nl il _ _) ->
      let nodes = Container.elems nl
          instances = Container.elems il
      in (sum . map (length . Node.pList)) nodes == 0 &&
         null instances

-- | Check that compareNameComponent on equal strings works.
prop_compareNameComponent_equal :: String -> Bool
prop_compareNameComponent_equal s =
  BasicTypes.compareNameComponent s s ==
    BasicTypes.LookupResult BasicTypes.ExactMatch s

-- | Check that compareNameComponent on prefix strings works.
prop_compareNameComponent_prefix :: NonEmptyList Char -> String -> Bool
prop_compareNameComponent_prefix (NonEmpty s1) s2 =
  BasicTypes.compareNameComponent (s1 ++ "." ++ s2) s1 ==
    BasicTypes.LookupResult BasicTypes.PartialMatch s1

testSuite "HTools/Loader"
            [ 'prop_lookupNode
            , 'prop_lookupInstance
            , 'prop_assignIndices
            , 'prop_mergeData
            , 'prop_compareNameComponent_equal
            , 'prop_compareNameComponent_prefix
            ]
