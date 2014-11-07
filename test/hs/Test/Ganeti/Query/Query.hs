{-# LANGUAGE TemplateHaskell, BangPatterns #-}
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

module Test.Ganeti.Query.Query (testQuery_Query) where

import Test.HUnit (Assertion, assertEqual)
import Test.QuickCheck hiding (Result)
import Test.QuickCheck.Monadic

import Data.Function (on)
import Data.List
import qualified Data.Map as Map
import Data.Maybe
import qualified Data.Set as Set
import Text.JSON (JSValue(..), showJSON)

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon
import Test.Ganeti.Objects (genEmptyCluster)

import Ganeti.BasicTypes
import Ganeti.Errors
import Ganeti.JSON
import Ganeti.Objects
import Ganeti.Query.Filter
import qualified Ganeti.Query.Group as Group
import Ganeti.Query.Language
import qualified Ganeti.Query.Node as Node
import Ganeti.Query.Query
import qualified Ganeti.Query.Job as Job
import Ganeti.Utils (sepSplit)

{-# ANN module "HLint: ignore Use camelCase" #-}

-- * Helpers

-- | Checks if a list of field definitions contains unknown fields.
hasUnknownFields :: [FieldDefinition] -> Bool
hasUnknownFields = (QFTUnknown `notElem`) . map fdefKind

-- * Test cases

-- ** Node queries

-- | Tests that querying any existing fields, via either query or
-- queryFields, will not return unknown fields.
prop_queryNode_noUnknown :: Property
prop_queryNode_noUnknown =
  forAll (choose (0, maxNodes) >>= genEmptyCluster) $ \cluster ->
  forAll (elements (Map.keys Node.fieldsMap)) $ \field -> monadicIO $ do
  QueryResult fdefs fdata <-
    run (query cluster False (Query (ItemTypeOpCode QRNode)
                              [field] EmptyFilter)) >>= resultProp
  QueryFieldsResult fdefs' <-
    resultProp $ queryFields (QueryFields (ItemTypeOpCode QRNode) [field])
  stop $ conjoin
         [ counterexample ("Got unknown fields via query (" ++
                           show fdefs ++ ")") (hasUnknownFields fdefs)
         , counterexample ("Got unknown result status via query (" ++
                           show fdata ++ ")")
           (all (all ((/= RSUnknown) . rentryStatus)) fdata)
         , counterexample ("Got unknown fields via query fields (" ++
                           show fdefs'++ ")") (hasUnknownFields fdefs')
         ]

-- | Tests that an unknown field is returned as such.
prop_queryNode_Unknown :: Property
prop_queryNode_Unknown =
  forAll (choose (0, maxNodes) >>= genEmptyCluster) $ \cluster ->
  forAll (arbitrary `suchThat` (`notElem` Map.keys Node.fieldsMap))
    $ \field -> monadicIO $ do
  QueryResult fdefs fdata <-
    run (query cluster False (Query (ItemTypeOpCode QRNode)
                              [field] EmptyFilter)) >>= resultProp
  QueryFieldsResult fdefs' <-
    resultProp $ queryFields (QueryFields (ItemTypeOpCode QRNode) [field])
  stop $ conjoin
         [ counterexample ("Got known fields via query (" ++ show fdefs ++ ")")
           (not $ hasUnknownFields fdefs)
         , counterexample ("Got /= ResultUnknown result status via query (" ++
                           show fdata ++ ")")
           (all (all ((== RSUnknown) . rentryStatus)) fdata)
         , counterexample ("Got a Just in a result value (" ++
                           show fdata ++ ")")
           (all (all (isNothing . rentryValue)) fdata)
         , counterexample ("Got known fields via query fields (" ++ show fdefs'
                           ++ ")") (not $ hasUnknownFields fdefs')
         ]

-- | Checks that a result type is conforming to a field definition.
checkResultType :: FieldDefinition -> ResultEntry -> Property
checkResultType _ (ResultEntry RSNormal Nothing) =
  failTest "Nothing result in RSNormal field"
checkResultType _ (ResultEntry _ Nothing) = passTest
checkResultType fdef (ResultEntry RSNormal (Just v)) =
  case (fdefKind fdef, v) of
    (QFTText      , JSString {})   -> passTest
    (QFTBool      , JSBool {})     -> passTest
    (QFTNumber    , JSRational {}) -> passTest
    (QFTNumberFloat , JSRational {}) -> passTest
    (QFTTimestamp , JSRational {}) -> passTest
    (QFTUnit      , JSRational {}) -> passTest
    (QFTOther     , _)             -> passTest -- meh, QFT not precise...
    (kind, _) -> failTest $ "Type mismatch, field definition says " ++
                  show kind ++ " but returned value is " ++ show v ++
                  " for field '" ++ fdefName fdef ++ "'"
checkResultType _ (ResultEntry r (Just _)) =
  failTest $ "Just result in " ++ show r ++ " field"

-- | Tests that querying any existing fields, the following three
-- properties hold: RSNormal corresponds to a Just value, any other
-- value corresponds to Nothing, and for a RSNormal and value field,
-- the type of the value corresponds to the type of the field as
-- declared in the FieldDefinition.
prop_queryNode_types :: Property
prop_queryNode_types =
  forAll (choose (0, maxNodes)) $ \numnodes ->
  forAll (genEmptyCluster numnodes) $ \cfg ->
  forAll (elements (Map.keys Node.fieldsMap)) $ \field -> monadicIO $ do
  QueryResult fdefs fdata <-
    run (query cfg False (Query (ItemTypeOpCode QRNode)
                          [field] EmptyFilter)) >>= resultProp
  stop $ conjoin
         [ counterexample ("Inconsistent result entries (" ++ show fdata ++ ")")
           (conjoin $ map (conjoin . zipWith checkResultType fdefs) fdata)
         , counterexample "Wrong field definitions length"
           (length fdefs ==? 1)
         , counterexample "Wrong field result rows length"
           (all ((== 1) . length) fdata)
         , counterexample "Wrong number of result rows"
           (length fdata ==? numnodes)
         ]

-- | Test that queryFields with empty fields list returns all node fields.
case_queryNode_allfields :: Assertion
case_queryNode_allfields = do
  fdefs <- case queryFields (QueryFields (ItemTypeOpCode QRNode) []) of
             Bad msg -> fail $ "Error in query all fields: " ++
                        formatError msg
             Ok (QueryFieldsResult v) -> return v
  let field_sort = compare `on` fdefName
  assertEqual "Mismatch in all fields list"
    (sortBy field_sort . map (\(f, _, _) -> f) $ Map.elems Node.fieldsMap)
    (sortBy field_sort fdefs)

-- | Check if cluster node names are unique (first elems).
areNodeNamesSane :: ConfigData -> Bool
areNodeNamesSane cfg =
  let fqdns = map nodeName . Map.elems . fromContainer $ configNodes cfg
      names = map (head . sepSplit '.') fqdns
  in length names == length (nub names)

-- | Check that the nodes reported by a name filter are sane.
prop_queryNode_filter :: Property
prop_queryNode_filter =
  forAll (choose (1, maxNodes)) $ \nodes ->
  forAll (genEmptyCluster nodes `suchThat`
          areNodeNamesSane) $ \cluster -> monadicIO $ do
    let node_list = map nodeName . Map.elems . fromContainer $
                    configNodes cluster
    count <- pick $ choose (1, nodes)
    fqdn_set <- pick . genSetHelper node_list $ Just count
    let fqdns = Set.elems fqdn_set
        names = map (head . sepSplit '.') fqdns
        flt = makeSimpleFilter "name" $ map Left names
    QueryResult _ fdata <-
      run (query cluster False (Query (ItemTypeOpCode QRNode)
                                ["name"] flt)) >>= resultProp
    stop $ conjoin
      [ counterexample "Invalid node names" $
        map (map rentryValue) fdata ==? map (\f -> [Just (showJSON f)]) fqdns
      ]

-- ** Group queries

prop_queryGroup_noUnknown :: Property
prop_queryGroup_noUnknown =
  forAll (choose (0, maxNodes) >>= genEmptyCluster) $ \cluster ->
  forAll (elements (Map.keys Group.fieldsMap)) $ \field -> monadicIO $ do
    QueryResult fdefs fdata <-
      run (query cluster False (Query (ItemTypeOpCode QRGroup)
                                [field] EmptyFilter)) >>=
           resultProp
    QueryFieldsResult fdefs' <-
      resultProp $ queryFields (QueryFields (ItemTypeOpCode QRGroup) [field])
    stop $ conjoin
     [ counterexample ("Got unknown fields via query (" ++ show fdefs ++ ")")
          (hasUnknownFields fdefs)
     , counterexample ("Got unknown result status via query (" ++
                       show fdata ++ ")")
       (all (all ((/= RSUnknown) . rentryStatus)) fdata)
     , counterexample ("Got unknown fields via query fields (" ++ show fdefs'
                       ++ ")") (hasUnknownFields fdefs')
     ]

prop_queryGroup_Unknown :: Property
prop_queryGroup_Unknown =
  forAll (choose (0, maxNodes) >>= genEmptyCluster) $ \cluster ->
  forAll (arbitrary `suchThat` (`notElem` Map.keys Group.fieldsMap))
    $ \field -> monadicIO $ do
  QueryResult fdefs fdata <-
    run (query cluster False (Query (ItemTypeOpCode QRGroup)
                              [field] EmptyFilter)) >>= resultProp
  QueryFieldsResult fdefs' <-
    resultProp $ queryFields (QueryFields (ItemTypeOpCode QRGroup) [field])
  stop $ conjoin
         [ counterexample ("Got known fields via query (" ++ show fdefs ++ ")")
           (not $ hasUnknownFields fdefs)
         , counterexample ("Got /= ResultUnknown result status via query (" ++
                           show fdata ++ ")")
           (all (all ((== RSUnknown) . rentryStatus)) fdata)
         , counterexample ("Got a Just in a result value (" ++
                           show fdata ++ ")")
           (all (all (isNothing . rentryValue)) fdata)
         , counterexample ("Got known fields via query fields (" ++ show fdefs'
                           ++ ")") (not $ hasUnknownFields fdefs')
         ]

prop_queryGroup_types :: Property
prop_queryGroup_types =
  forAll (choose (0, maxNodes)) $ \numnodes ->
  forAll (genEmptyCluster numnodes) $ \cfg ->
  forAll (elements (Map.keys Group.fieldsMap)) $ \field -> monadicIO $ do
  QueryResult fdefs fdata <-
    run (query cfg False (Query (ItemTypeOpCode QRGroup)
                          [field] EmptyFilter)) >>= resultProp
  stop $ conjoin
         [ counterexample ("Inconsistent result entries (" ++ show fdata ++ ")")
           (conjoin $ map (conjoin . zipWith checkResultType fdefs) fdata)
         , counterexample "Wrong field definitions length" (length fdefs ==? 1)
         , counterexample "Wrong field result rows length"
           (all ((== 1) . length) fdata)
         ]

case_queryGroup_allfields :: Assertion
case_queryGroup_allfields = do
  fdefs <- case queryFields (QueryFields (ItemTypeOpCode QRGroup) []) of
             Bad msg -> fail $ "Error in query all fields: " ++
                        formatError msg
             Ok (QueryFieldsResult v) -> return v
  let field_sort = compare `on` fdefName
  assertEqual "Mismatch in all fields list"
    (sortBy field_sort . map (\(f, _, _) -> f) $ Map.elems Group.fieldsMap)
    (sortBy field_sort fdefs)

-- | Check that the node count reported by a group list is sane.
--
-- FIXME: also verify the node list, etc.
prop_queryGroup_nodeCount :: Property
prop_queryGroup_nodeCount =
  forAll (choose (0, maxNodes)) $ \nodes ->
  forAll (genEmptyCluster nodes) $ \cluster -> monadicIO $
  do
    QueryResult _ fdata <-
      run (query cluster False (Query (ItemTypeOpCode QRGroup)
                                ["node_cnt"] EmptyFilter)) >>= resultProp
    stop $ conjoin
      [ counterexample "Invalid node count" $
        map (map rentryValue) fdata ==? [[Just (showJSON nodes)]]
      ]

-- ** Job queries

-- | Tests that querying any existing fields, via either query or
-- queryFields, will not return unknown fields. This uses 'undefined'
-- for config, as job queries shouldn't use the configuration, and an
-- explicit filter as otherwise non-live queries wouldn't return any
-- result rows.
prop_queryJob_noUnknown :: Property
prop_queryJob_noUnknown =
  forAll (listOf (arbitrary::Gen (Positive Integer))) $ \ids ->
  forAll (elements (Map.keys Job.fieldsMap)) $ \field -> monadicIO $ do
  let qtype = ItemTypeLuxi QRJob
      flt = makeSimpleFilter (nameField qtype) $
            map (\(Positive i) -> Right i) ids
  QueryResult fdefs fdata <-
    run (query undefined False (Query qtype [field] flt)) >>= resultProp
  QueryFieldsResult fdefs' <-
    resultProp $ queryFields (QueryFields qtype [field])
  stop $ conjoin
         [ counterexample ("Got unknown fields via query (" ++
                           show fdefs ++ ")") (hasUnknownFields fdefs)
         , counterexample ("Got unknown result status via query (" ++
                           show fdata ++ ")")
           (all (all ((/= RSUnknown) . rentryStatus)) fdata)
         , counterexample ("Got unknown fields via query fields (" ++
                           show fdefs'++ ")") (hasUnknownFields fdefs')
         ]

-- | Tests that an unknown field is returned as such.
prop_queryJob_Unknown :: Property
prop_queryJob_Unknown =
  forAll (listOf (arbitrary::Gen (Positive Integer))) $ \ids ->
  forAll (arbitrary `suchThat` (`notElem` Map.keys Job.fieldsMap))
    $ \field -> monadicIO $ do
  let qtype = ItemTypeLuxi QRJob
      flt = makeSimpleFilter (nameField qtype) $
            map (\(Positive i) -> Right i) ids
  QueryResult fdefs fdata <-
    run (query undefined False (Query qtype [field] flt)) >>= resultProp
  QueryFieldsResult fdefs' <-
    resultProp $ queryFields (QueryFields qtype [field])
  stop $ conjoin
         [ counterexample ("Got known fields via query (" ++ show fdefs ++ ")")
           (not $ hasUnknownFields fdefs)
         , counterexample ("Got /= ResultUnknown result status via query (" ++
                           show fdata ++ ")")
           (all (all ((== RSUnknown) . rentryStatus)) fdata)
         , counterexample ("Got a Just in a result value (" ++
                           show fdata ++ ")")
           (all (all (isNothing . rentryValue)) fdata)
         , counterexample ("Got known fields via query fields (" ++ show fdefs'
                           ++ ")") (not $ hasUnknownFields fdefs')
         ]

-- ** Misc other tests

-- | Tests that requested names checking behaves as expected.
prop_getRequestedNames :: Property
prop_getRequestedNames =
  forAll genName $ \node1 ->
  let chk = getRequestedNames . Query (ItemTypeOpCode QRNode) []
      q_node1 = QuotedString node1
      eq_name = EQFilter "name"
      eq_node1 = eq_name q_node1
  in conjoin [ counterexample "empty filter" $ chk EmptyFilter ==? []
             , counterexample "and filter" $ chk (AndFilter [eq_node1]) ==? []
             , counterexample "simple equality" $ chk eq_node1 ==? [node1]
             , counterexample "non-name field" $
               chk (EQFilter "foo" q_node1) ==? []
             , counterexample "non-simple filter" $
               chk (OrFilter [ eq_node1 , LTFilter "foo" q_node1]) ==? []
             ]

testSuite "Query/Query"
  [ 'prop_queryNode_noUnknown
  , 'prop_queryNode_Unknown
  , 'prop_queryNode_types
  , 'prop_queryNode_filter
  , 'case_queryNode_allfields
  , 'prop_queryGroup_noUnknown
  , 'prop_queryGroup_Unknown
  , 'prop_queryGroup_types
  , 'case_queryGroup_allfields
  , 'prop_queryGroup_nodeCount
  , 'prop_queryJob_noUnknown
  , 'prop_queryJob_Unknown
  , 'prop_getRequestedNames
  ]
