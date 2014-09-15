{-# LANGUAGE TemplateHaskell #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Unittests for 'Ganeti.THH.Types'.

-}

{-

Copyright (C) 2014 Google Inc.
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

module Test.Ganeti.THH.Types
  ( testTHH_Types
  ) where

import Test.QuickCheck as QuickCheck hiding (Result)
import qualified Text.JSON as J

import Test.Ganeti.TestCommon
import Test.Ganeti.TestHelper

import Ganeti.THH.Types

{-# ANN module "HLint: ignore Use camelCase" #-}

-- * Instances

instance Arbitrary a => Arbitrary (OneTuple a) where
  arbitrary = fmap OneTuple arbitrary

-- * Properties

-- | Tests OneTuple serialisation.
prop_OneTuple_serialisation :: OneTuple String -> Property
prop_OneTuple_serialisation = testSerialisation

-- | Tests OneTuple doesn't deserialize wrong input.
prop_OneTuple_deserialisationFail :: Property
prop_OneTuple_deserialisationFail =
  conjoin . map (testDeserialisationFail (OneTuple "")) $
    [ J.JSArray []
    , J.JSArray [J.showJSON "a", J.showJSON "b"]
    , J.JSArray [J.showJSON (1 :: Int)]
    ]


-- * Test suite

testSuite "THH_Types"
  [ 'prop_OneTuple_serialisation
  , 'prop_OneTuple_deserialisationFail
  ]
