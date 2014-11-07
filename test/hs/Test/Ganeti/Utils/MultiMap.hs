{-# LANGUAGE TemplateHaskell #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Unittests for mutli-maps

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

module Test.Ganeti.Utils.MultiMap
  ( testUtils_MultiMap
  ) where

import Control.Applicative
import qualified Data.Set as S
import qualified Data.Map as M

import Test.QuickCheck

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon

import Ganeti.Utils.MultiMap as MM

instance (Arbitrary k, Ord k, Arbitrary v, Ord v)
         => Arbitrary (MultiMap k v) where
  arbitrary = frequency
    [ (1, (multiMap . M.fromList)
          <$> listOf ((,) <$> arbitrary
                          <*> (S.fromList <$> listOf arbitrary)))
    , (4, MM.insert <$> arbitrary <*> arbitrary <*> arbitrary)
    , (1, MM.fromList <$> listOf ((,) <$> arbitrary <*> arbitrary))
    , (3, MM.delete <$> arbitrary <*> arbitrary <*> arbitrary)
    , (1, MM.deleteAll <$> arbitrary <*> arbitrary)
    ]

-- | A data type for testing extensional equality.
data Three = One | Two | Three
  deriving (Eq, Ord, Show, Enum, Bounded)

instance Arbitrary Three where
  arbitrary = elements [minBound..maxBound]

-- | Tests the extensional equality of multi-maps.
prop_MultiMap_equality
  :: MultiMap Three Three -> MultiMap Three Three -> Property
prop_MultiMap_equality m1 m2 =
  let testKey k = MM.lookup k m1 == MM.lookup k m2
   in counterexample ("Extensional equality of '" ++ show m1
                      ++ "' and '" ++ show m2 ++ " doesn't match '=='.")
      $ all testKey [minBound..maxBound] ==? (m1 == m2)

prop_MultiMap_serialisation :: MultiMap Int Int -> Property
prop_MultiMap_serialisation = testSerialisation

testSuite "Utils/MultiMap"
  [ 'prop_MultiMap_equality
  , 'prop_MultiMap_serialisation
  ]
