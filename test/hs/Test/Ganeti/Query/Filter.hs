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

module Test.Ganeti.Query.Filter (testQuery_Filter) where

import Test.QuickCheck hiding (Result)
import Test.QuickCheck.Monadic

import qualified Data.ByteString.UTF8 as UTF8
import qualified Data.Map as Map
import Data.List
import Text.JSON (showJSON)

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon
import Test.Ganeti.Objects (genEmptyCluster)

import Ganeti.BasicTypes
import Ganeti.JSON
import Ganeti.Objects
import Ganeti.Query.Filter
import Ganeti.Query.Language
import Ganeti.Query.Query
import Ganeti.Utils (niceSort)

-- * Helpers

-- | Run a query and check that we got a specific response.
checkQueryResults :: ConfigData -> Query -> String
                  -> [[ResultEntry]] -> Property
checkQueryResults cfg qr descr expected = monadicIO $ do
  result <- run (query cfg False qr) >>= resultProp
  stop $ counterexample ("Inconsistent results in " ++ descr)
         (qresData result ==? expected)

-- | Makes a node name query, given a filter.
makeNodeQuery :: Filter FilterField -> Query
makeNodeQuery = Query (ItemTypeOpCode QRNode) ["name"]

-- | Checks if a given operation failed.
expectBadQuery :: ConfigData -> Query -> String -> Property
expectBadQuery cfg qr descr = monadicIO $ do
  result <- run (query cfg False qr)
  case result of
    Bad _ -> return ()
    Ok a  -> stop . failTest $ "Expected failure in " ++ descr ++
                               " but got " ++ show a

-- | A helper to construct a list of results from an expected names list.
namesToResult :: [String] -> [[ResultEntry]]
namesToResult = map ((:[]) . ResultEntry RSNormal . Just . showJSON)

-- | Generates a cluster and returns its node names too.
genClusterNames :: Int -> Int -> Gen (ConfigData, [String])
genClusterNames min_nodes max_nodes = do
  numnodes <- choose (min_nodes, max_nodes)
  cfg <- genEmptyCluster numnodes
  return (cfg , niceSort . map UTF8.toString . Map.keys . fromContainer
                  $ configNodes cfg)

-- * Test cases

-- | Tests single node filtering: eq should return it, and (lt and gt)
-- should fail.
prop_node_single_filter :: Property
prop_node_single_filter =
  forAll (genClusterNames 1 maxNodes) $ \(cfg, allnodes) ->
  forAll (elements allnodes) $ \nname ->
  let fvalue = QuotedString nname
      buildflt n = n "name" fvalue
      expsingle = namesToResult [nname]
      othernodes = nname `delete` allnodes
      expnot = namesToResult othernodes
      test_query = checkQueryResults cfg . makeNodeQuery
  in conjoin
       [ test_query (buildflt EQFilter) "single-name 'EQ' filter" expsingle
       , test_query (NotFilter (buildflt EQFilter))
         "single-name 'NOT EQ' filter" expnot
       , test_query (AndFilter [buildflt LTFilter, buildflt GTFilter])
         "single-name 'AND [LT,GT]' filter" []
       , test_query (AndFilter [buildflt LEFilter, buildflt GEFilter])
         "single-name 'And [LE,GE]' filter" expsingle
       ]

-- | Tests node filtering based on name equality: many 'OrFilter'
-- should return all results combined, many 'AndFilter' together
-- should return nothing. Note that we need at least 2 nodes so that
-- the 'AndFilter' case breaks.
prop_node_many_filter :: Property
prop_node_many_filter =
  forAll (genClusterNames 2 maxNodes) $ \(cfg, nnames) ->
  let eqfilter = map (EQFilter "name" . QuotedString) nnames
      alln = namesToResult nnames
      test_query = checkQueryResults cfg . makeNodeQuery
      num_zero = NumericValue 0
  in conjoin
     [ test_query (OrFilter eqfilter) "all nodes 'Or' name filter" alln
     , test_query (AndFilter eqfilter) "all nodes 'And' name filter" []
     -- this next test works only because genEmptyCluster generates a
     -- cluster with no instances
     , test_query (EQFilter "pinst_cnt" num_zero) "pinst_cnt 'Eq' 0" alln
     , test_query (GTFilter "sinst_cnt" num_zero) "sinst_cnt 'GT' 0" []
     ]

-- | Tests name ordering consistency: requesting a 'simple filter'
-- results in identical name ordering as the wanted names, requesting
-- a more complex filter results in a niceSort-ed order.
prop_node_name_ordering :: Property
prop_node_name_ordering =
  forAll (genClusterNames 2 6) $ \(cfg, nnames) ->
  forAll (elements (subsequences nnames)) $ \sorted_nodes ->
  forAll (elements (permutations sorted_nodes)) $ \chosen_nodes ->
  let orfilter = OrFilter $ map (EQFilter "name" . QuotedString) chosen_nodes
      alln = namesToResult chosen_nodes
      all_sorted = namesToResult $ niceSort chosen_nodes
      test_query = checkQueryResults cfg . makeNodeQuery
  in conjoin
     [ test_query orfilter "simple filter/requested" alln
     , test_query (AndFilter [orfilter]) "complex filter/sorted" all_sorted
     ]

-- | Tests node regex filtering. This is a very basic test :(
prop_node_regex_filter :: Property
prop_node_regex_filter =
  forAll (genClusterNames 0 maxNodes) $ \(cfg, nnames) ->
  case mkRegex ".*"::Result FilterRegex of
    Bad msg -> failTest $ "Can't build regex?! Error: " ++ msg
    Ok rx ->
      checkQueryResults cfg (makeNodeQuery (RegexpFilter "name" rx))
        "rows for all nodes regexp filter" $ namesToResult nnames

-- | Tests node regex filtering. This is a very basic test :(
prop_node_bad_filter :: String -> Int -> Property
prop_node_bad_filter rndname rndint =
  forAll (genClusterNames 1 maxNodes) $ \(cfg, _) ->
  let test_query = expectBadQuery cfg . makeNodeQuery
      string_value = QuotedString rndname
      numeric_value = NumericValue $ fromIntegral rndint
  in case mkRegex ".*"::Result FilterRegex of
       Bad msg -> failTest $ "Can't build regex?! Error: " ++ msg
       Ok rx ->
         conjoin
           [ test_query (RegexpFilter "offline" rx)
             "regex filter against boolean field"
           , test_query (EQFilter "name" numeric_value)
             "numeric value eq against string field"
           , test_query (TrueFilter "name")
             "true filter against string field"
           , test_query (EQFilter "offline" string_value)
             "quoted string eq against boolean field"
           , test_query (ContainsFilter "name" string_value)
             "quoted string in non-list field"
           , test_query (ContainsFilter "name" numeric_value)
             "numeric value in non-list field"
           ]

-- | Tests make simple filter.
prop_makeSimpleFilter :: Property
prop_makeSimpleFilter =
  forAll (resize 10 $ listOf1 genName) $ \names ->
  forAll (resize 10 $ listOf1 arbitrary) $ \ids ->
  forAll genName $ \namefield ->
  conjoin [ counterexample "test expected names" $
              makeSimpleFilter namefield (map Left names) ==?
              OrFilter (map (EQFilter namefield . QuotedString) names)
          , counterexample "test expected IDs" $
              makeSimpleFilter namefield (map Right ids) ==?
              OrFilter (map (EQFilter namefield . NumericValue) ids)
          , counterexample "test empty names" $
              makeSimpleFilter namefield [] ==? EmptyFilter
          ]

testSuite "Query/Filter"
  [ 'prop_node_single_filter
  , 'prop_node_many_filter
  , 'prop_node_name_ordering
  , 'prop_node_regex_filter
  , 'prop_node_bad_filter
  , 'prop_makeSimpleFilter
  ]
