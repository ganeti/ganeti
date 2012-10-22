{-# LANGUAGE TemplateHaskell #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Unittests for ganeti-htools.

-}

{-

Copyright (C) 2009, 2010, 2011, 2012 Google Inc.

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

module Test.Ganeti.HTools.Container (testHTools_Container) where

import Test.QuickCheck

import Data.Maybe

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon
import Test.Ganeti.TestHTools
import Test.Ganeti.HTools.Node (genNode)

import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Node as Node

-- we silence the following due to hlint bug fixed in later versions
{-# ANN prop_addTwo "HLint: ignore Avoid lambda" #-}
prop_addTwo :: [Container.Key] -> Int -> Int -> Bool
prop_addTwo cdata i1 i2 =
  fn i1 i2 cont == fn i2 i1 cont &&
  fn i1 i2 cont == fn i1 i2 (fn i1 i2 cont)
    where cont = foldl (\c x -> Container.add x x c) Container.empty cdata
          fn x1 x2 = Container.addTwo x1 x1 x2 x2

prop_nameOf :: Node.Node -> Property
prop_nameOf node =
  let nl = makeSmallCluster node 1
      fnode = head (Container.elems nl)
  in Container.nameOf nl (Node.idx fnode) ==? Node.name fnode

-- | We test that in a cluster, given a random node, we can find it by
-- its name and alias, as long as all names and aliases are unique,
-- and that we fail to find a non-existing name.
prop_findByName :: Property
prop_findByName =
  forAll (genNode (Just 1) Nothing) $ \node ->
  forAll (choose (1, 20)) $ \ cnt ->
  forAll (choose (0, cnt - 1)) $ \ fidx ->
  forAll (genUniquesList (cnt * 2)) $ \ allnames ->
  forAll (arbitrary `suchThat` (`notElem` allnames)) $ \ othername ->
  let names = zip (take cnt allnames) (drop cnt allnames)
      nl = makeSmallCluster node cnt
      nodes = Container.elems nl
      nodes' = map (\((name, alias), nn) -> (Node.idx nn,
                                             nn { Node.name = name,
                                                  Node.alias = alias }))
               $ zip names nodes
      nl' = Container.fromList nodes'
      target = snd (nodes' !! fidx)
  in conjoin
       [ Container.findByName nl' (Node.name target) ==? Just target
       , Container.findByName nl' (Node.alias target) ==? Just target
       , printTestCase "Found non-existing name"
         (isNothing (Container.findByName nl' othername))
       ]

testSuite "HTools/Container"
            [ 'prop_addTwo
            , 'prop_nameOf
            , 'prop_findByName
            ]
