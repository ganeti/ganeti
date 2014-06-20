{-| Common tests for PartialParams instances

-}

{-

Copyright (C) 2012 Google Inc.
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

module Test.Ganeti.PartialParams
  ( testFillParamsLaw1
  , testToParamsLaw2
  , testToFilledLaw3
  , testToFilledMonoidLaw1
  , testToFilledMonoidLaw2
  ) where

import Data.Monoid

import Test.QuickCheck

import Ganeti.PartialParams

import Test.Ganeti.TestCommon

-- | Checks for serialisation idempotence.
testFillParamsLaw1 :: (PartialParams f p, Show f, Eq f)
                   => f -> p -> Property
testFillParamsLaw1 f p = fillParams (fillParams f p) p ==? fillParams f p

-- | Tests that filling partial parameters satisfies the law.
testToParamsLaw2 :: (PartialParams f p, Show f, Eq f) => f -> f -> Property
testToParamsLaw2 x f = fillParams x (toPartial f) ==? f

-- | Tests that converting partial to filled parameters satisfies the law.
testToFilledLaw3 :: (PartialParams f p, Show f, Eq f) => f -> Property
testToFilledLaw3 f = toFilled (toPartial f) ==? Just f

-- | Tests that the partial params behave correctly as a monoid action.
testToFilledMonoidLaw1 :: (PartialParams f p, Show f, Eq f, Monoid p)
                       => f -> Property
testToFilledMonoidLaw1 f = fillParams f mempty ==? f

-- | Tests that the partial params behave correctly as a monoid action.
testToFilledMonoidLaw2 :: (PartialParams f p, Show f, Eq f, Monoid p)
                       => f -> p -> p -> Property
testToFilledMonoidLaw2 f p1 p2 =
  fillParams f (p1 <> p2) ==? fillParams (fillParams f p1) p2
