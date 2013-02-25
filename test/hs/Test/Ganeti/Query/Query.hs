{-# LANGUAGE TemplateHaskell #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Unittests for ganeti-htools.

-}

{-

Copyright (C) 2009, 2010, 2011, 2012, 2013 Google Inc.

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

module Test.Ganeti.Query.Query (testQuery_Query) where

import Test.HUnit (Assertion, assertEqual)
import Test.QuickCheck hiding (Result)
import Test.QuickCheck.Monadic

import Data.Function (on)
import Data.List
import qualified Data.Map as Map
import Data.Maybe
import Text.JSON (JSValue(..), showJSON)

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon
import Test.Ganeti.Objects (genEmptyCluster)

import Ganeti.BasicTypes
import Ganeti.Errors
import Ganeti.Query.Filter
import qualified Ganeti.Query.Group as Group
import Ganeti.Query.Language
import qualified Ganeti.Query.Node as Node
import Ganeti.Query.Query
import qualified Ganeti.Query.Job as Job

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
         [ printTestCase ("Got unknown fields via query (" ++
                          show fdefs ++ ")") (hasUnknownFields fdefs)
         , printTestCase ("Got unknown result status via query (" ++
                          show fdata ++ ")")
           (all (all ((/= RSUnknown) . rentryStatus)) fdata)
         , printTestCase ("Got unknown fields via query fields (" ++
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
         [ printTestCase ("Got known fields via query (" ++ show fdefs ++ ")")
           (not $ hasUnknownFields fdefs)
         , printTestCase ("Got /= ResultUnknown result status via query (" ++
                          show fdata ++ ")")
           (all (all ((== RSUnknown) . rentryStatus)) fdata)
         , printTestCase ("Got a Just in a result value (" ++
                          show fdata ++ ")")
           (all (all (isNothing . rentryValue)) fdata)
         , printTestCase ("Got known fields via query fields (" ++ show fdefs'
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
         [ printTestCase ("Inconsistent result entries (" ++ show fdata ++ ")")
           (conjoin $ map (conjoin . zipWith checkResultType fdefs) fdata)
         , printTestCase "Wrong field definitions length"
           (length fdefs ==? 1)
         , printTestCase "Wrong field result rows length"
           (all ((== 1) . length) fdata)
         , printTestCase "Wrong number of result rows"
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
     [ printTestCase ("Got unknown fields via query (" ++ show fdefs ++ ")")
          (hasUnknownFields fdefs)
     , printTestCase ("Got unknown result status via query (" ++
                      show fdata ++ ")")
       (all (all ((/= RSUnknown) . rentryStatus)) fdata)
     , printTestCase ("Got unknown fields via query fields (" ++ show fdefs'
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
         [ printTestCase ("Got known fields via query (" ++ show fdefs ++ ")")
           (not $ hasUnknownFields fdefs)
         , printTestCase ("Got /= ResultUnknown result status via query (" ++
                          show fdata ++ ")")
           (all (all ((== RSUnknown) . rentryStatus)) fdata)
         , printTestCase ("Got a Just in a result value (" ++
                          show fdata ++ ")")
           (all (all (isNothing . rentryValue)) fdata)
         , printTestCase ("Got known fields via query fields (" ++ show fdefs'
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
         [ printTestCase ("Inconsistent result entries (" ++ show fdata ++ ")")
           (conjoin $ map (conjoin . zipWith checkResultType fdefs) fdata)
         , printTestCase "Wrong field definitions length" (length fdefs ==? 1)
         , printTestCase "Wrong field result rows length"
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
      [ printTestCase "Invalid node count" $
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
         [ printTestCase ("Got unknown fields via query (" ++
                          show fdefs ++ ")") (hasUnknownFields fdefs)
         , printTestCase ("Got unknown result status via query (" ++
                          show fdata ++ ")")
           (all (all ((/= RSUnknown) . rentryStatus)) fdata)
         , printTestCase ("Got unknown fields via query fields (" ++
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
         [ printTestCase ("Got known fields via query (" ++ show fdefs ++ ")")
           (not $ hasUnknownFields fdefs)
         , printTestCase ("Got /= ResultUnknown result status via query (" ++
                          show fdata ++ ")")
           (all (all ((== RSUnknown) . rentryStatus)) fdata)
         , printTestCase ("Got a Just in a result value (" ++
                          show fdata ++ ")")
           (all (all (isNothing . rentryValue)) fdata)
         , printTestCase ("Got known fields via query fields (" ++ show fdefs'
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
  in conjoin [ printTestCase "empty filter" $ chk EmptyFilter ==? []
             , printTestCase "and filter" $ chk (AndFilter [eq_node1]) ==? []
             , printTestCase "simple equality" $ chk eq_node1 ==? [node1]
             , printTestCase "non-name field" $
               chk (EQFilter "foo" q_node1) ==? []
             , printTestCase "non-simple filter" $
               chk (OrFilter [ eq_node1 , LTFilter "foo" q_node1]) ==? []
             ]

testSuite "Query/Query"
  [ 'prop_queryNode_noUnknown
  , 'prop_queryNode_Unknown
  , 'prop_queryNode_types
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
