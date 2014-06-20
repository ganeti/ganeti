{-# LANGUAGE FunctionalDependencies #-}

{-| Common functions for partial parameters -}

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

module Ganeti.PartialParams
  ( PartialParams(..)
  , isComplete
  ) where

import Data.Maybe (isJust)

-- | Represents that data type @p@ provides partial values for
-- data type @f@.
--
-- Note: To avoid needless type annotations, the functional dependencies
-- currently include @f -> p@. However, in theory it'd be possible for one
-- filled data type to have several partially filled ones.
--
-- Laws:
--
-- 1. @fillParams (fillParams f p) p = fillParams f p@.
-- 2. @fillParams _ (toPartial x) = x@.
-- 3. @toFilled (toPartial x) = Just x@.
--
-- If @p@ is also a 'Monoid' (or just 'Semigroup'), 'fillParams' is a monoid
-- (semigroup) action on @f@, therefore it should additionally satisfy:
--
-- - @fillParams f mempty = f@
-- - @fillParams f (p1 <> p2) = fillParams (fillParams f p1) p2@
class PartialParams f p | p -> f, f -> p where
  -- | Fill @f@ with any data that are set in @p@.
  -- Leave other parts of @f@ unchanged.
  fillParams :: f -> p -> f
  -- | Fill all fields of @p@ from @f@.
  toPartial :: f -> p
  -- | If all fields of @p@ are filled, convert it into @f@.
  toFilled :: p -> Maybe f

-- | Returns 'True' if a given partial parameters are complete.
-- See 'toFilled'.
isComplete :: (PartialParams f p) => p -> Bool
isComplete = isJust . toFilled
