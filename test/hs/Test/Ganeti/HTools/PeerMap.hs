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

module Test.Ganeti.HTools.PeerMap (testHTools_PeerMap) where

import Test.QuickCheck

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon

import qualified Ganeti.HTools.PeerMap as PeerMap

-- | Make sure add is idempotent.
prop_addIdempotent :: PeerMap.PeerMap
                   -> PeerMap.Key -> PeerMap.Elem -> Property
prop_addIdempotent pmap key em =
  fn (fn puniq) ==? fn puniq
    where fn = PeerMap.add key em
          puniq = PeerMap.accumArray const pmap

-- | Make sure remove is idempotent.
prop_removeIdempotent :: PeerMap.PeerMap -> PeerMap.Key -> Property
prop_removeIdempotent pmap key =
  fn (fn puniq) ==? fn puniq
    where fn = PeerMap.remove key
          puniq = PeerMap.accumArray const pmap

-- | Make sure a missing item returns 0.
prop_findMissing :: PeerMap.PeerMap -> PeerMap.Key -> Property
prop_findMissing pmap key =
  PeerMap.find key (PeerMap.remove key puniq) ==? 0
    where puniq = PeerMap.accumArray const pmap

-- | Make sure an added item is found.
prop_addFind :: PeerMap.PeerMap
                     -> PeerMap.Key -> PeerMap.Elem -> Property
prop_addFind pmap key em =
  PeerMap.find key (PeerMap.add key em puniq) ==? em
    where puniq = PeerMap.accumArray const pmap

-- | Manual check that maxElem returns the maximum indeed, or 0 for null.
prop_maxElem :: PeerMap.PeerMap -> Property
prop_maxElem pmap =
  PeerMap.maxElem puniq ==? if null puniq then 0
                              else (maximum . snd . unzip) puniq
    where puniq = PeerMap.accumArray const pmap

-- | List of tests for the PeerMap module.
testSuite "HTools/PeerMap"
            [ 'prop_addIdempotent
            , 'prop_removeIdempotent
            , 'prop_maxElem
            , 'prop_addFind
            , 'prop_findMissing
            ]
