{-

Copyright (C) 2009, 2010, 2011 Google Inc.

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

module Ganeti.BasicTypes
  ( Result(..)
  , isOk
  , isBad
  , eitherToResult
  ) where

import Control.Monad

-- | This is similar to the JSON library Result type - /very/ similar,
-- but we want to use it in multiple places, so we abstract it into a
-- mini-library here.
--
-- The failure value for this monad is simply a string.
data Result a
    = Bad String
    | Ok a
    deriving (Show, Read, Eq)

instance Monad Result where
  (>>=) (Bad x) _ = Bad x
  (>>=) (Ok x) fn = fn x
  return = Ok
  fail = Bad

instance MonadPlus Result where
  mzero = Bad "zero Result when used as MonadPlus"
  -- for mplus, when we 'add' two Bad values, we concatenate their
  -- error descriptions
  (Bad x) `mplus` (Bad y) = Bad (x ++ "; " ++ y)
  (Bad _) `mplus` x = x
  x@(Ok _) `mplus` _ = x

-- | Simple checker for whether a 'Result' is OK.
isOk :: Result a -> Bool
isOk (Ok _) = True
isOk _ = False

-- | Simple checker for whether a 'Result' is a failure.
isBad :: Result a  -> Bool
isBad = not . isOk

-- | Converter from Either String to 'Result'.
eitherToResult :: Either String a -> Result a
eitherToResult (Left s) = Bad s
eitherToResult (Right v) = Ok v
