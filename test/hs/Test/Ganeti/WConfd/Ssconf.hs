{-# LANGUAGE TemplateHaskell #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Unittests for Ssconf writing

-}

{-

Copyright (C) 2015 Google Inc.
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

module Test.Ganeti.WConfd.Ssconf (testWConfd_Ssconf) where

import Test.QuickCheck

import qualified Data.Map as M
import qualified Data.Set as S

import Test.Ganeti.Objects ()
import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon

import Ganeti.Objects (ConfigData)
import qualified Ganeti.Ssconf as Ssconf
import qualified Ganeti.WConfd.Ssconf as Ssconf

-- * Ssconf construction tests

hasAllKeys :: Ssconf.SSConf -> Property
hasAllKeys ssc =
  counterexample "Missing SSConf key in the output" $
    M.keysSet (Ssconf.getSSConf ssc) ==? S.fromList [minBound..maxBound]

prop_mkSSConf_all_keys :: ConfigData -> Property
prop_mkSSConf_all_keys = hasAllKeys . Ssconf.mkSSConf

testSuite "WConfd/Ssconf"
  [ 'prop_mkSSConf_all_keys
  ]
