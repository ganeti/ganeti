{-# LANGUAGE TemplateHaskell #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Unittests for ganeti-htools.

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
  in case Container.elems nl of
       [] -> failTest "makeSmallCluster 1 returned empty cluster?"
       _:_:_ -> failTest "makeSmallCluster 1 returned >1 node?"
       fnode:_ -> Container.nameOf nl (Node.idx fnode) ==? Node.name fnode

-- | We test that in a cluster, given a random node, we can find it by
-- its name and alias, as long as all names and aliases are unique,
-- and that we fail to find a non-existing name.
prop_findByName :: Property
prop_findByName =
  forAll (genNode (Just 1) Nothing) $ \node ->
  forAll (choose (1, 20)) $ \ cnt ->
  forAll (choose (0, cnt - 1)) $ \ fidx ->
  forAll (genUniquesList (cnt * 2) arbitrary) $ \ allnames ->
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
       , counterexample "Found non-existing name"
         (isNothing (Container.findByName nl' othername))
       ]

testSuite "HTools/Container"
            [ 'prop_addTwo
            , 'prop_nameOf
            , 'prop_findByName
            ]
