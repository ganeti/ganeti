{-# LANGUAGE TemplateHaskell #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Unittests for query aliases.

-}

{-

Copyright (C) 2013 Google Inc.
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
