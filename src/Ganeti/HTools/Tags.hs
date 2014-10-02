{-| Tags

This module holds all the tag interpretation done by htools.

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

module Ganeti.HTools.Tags
  ( exTagsPrefix
  , standbyAuto
  , hasStandbyTag
  ) where

import Data.List (isPrefixOf)

import qualified Ganeti.HTools.Node as Node

-- * Constants

-- | The exclusion tag prefix. Instance tags starting with this prefix
-- describe a service provided by the instance. Instances providing the
-- same service at not places on the same node.
exTagsPrefix :: String
exTagsPrefix = "htools:iextags:"

-- | The tag-prefix indicating that hsqueeze should consider a node
-- as being standby.
standbyPrefix :: String
standbyPrefix = "htools:standby:"

-- | The tag to be added to nodes that were shutdown by hsqueeze.
standbyAuto :: String
standbyAuto = "htools:standby:auto"

-- * Predicates

-- | Predicate of having a standby tag.
hasStandbyTag :: Node.Node -> Bool
hasStandbyTag = any (standbyPrefix `isPrefixOf`) . Node.nTags

