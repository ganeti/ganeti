{-# LANGUAGE TemplateHaskell #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Unittests for query aliases.

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

module Test.Ganeti.Query.Aliases
  ( testQuery_Aliases
  ) where

import Data.List

import Test.Ganeti.TestHelper
import Test.HUnit

import Ganeti.Query.Common ()
import qualified Ganeti.Query.Instance as I
import Ganeti.Query.Language
import Ganeti.Query.Types

{-# ANN module "HLint: ignore Use camelCase" #-}

-- | Converts field list to field name list
toFieldNameList :: FieldList a b -> [FieldName]
toFieldNameList = map (\(x,_,_) -> fdefName x)

-- | Converts alias list to alias name list
toAliasNameList :: [(FieldName, FieldName)] -> [FieldName]
toAliasNameList = map fst

-- | Converts alias list to alias target list
toAliasTargetList :: [(FieldName, FieldName)] -> [FieldName]
toAliasTargetList = map snd

-- | Checks for shadowing
checkShadowing :: String
               -> FieldList a b
               -> [(FieldName, FieldName)]
               -> Assertion
checkShadowing name fields aliases =
  assertBool (name ++ " aliases do not shadow fields") .
    null $ toFieldNameList fields `intersect` toAliasNameList aliases

-- | Checks for target existence
checkTargets :: String
             -> FieldList a b
             -> [(FieldName, FieldName)]
             -> Assertion
checkTargets name fields aliases =
  assertBool (name ++ " alias targets exist") .
    null $ toAliasTargetList aliases \\ toFieldNameList fields

-- | Check that instance aliases do not shadow existing fields
case_instanceAliasesNoShadowing :: Assertion
case_instanceAliasesNoShadowing =
  checkShadowing "Instance" I.instanceFields I.instanceAliases

-- | Check that instance alias targets exist
case_instanceAliasesTargetsExist :: Assertion
case_instanceAliasesTargetsExist =
  checkTargets "Instance" I.instanceFields I.instanceAliases

testSuite "Query/Aliases"
  [ 'case_instanceAliasesNoShadowing,
    'case_instanceAliasesTargetsExist
  ]
