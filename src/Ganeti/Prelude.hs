{-# LANGUAGE NoImplicitPrelude, CPP #-}

{-| Export Prelude as in base 4.8.0

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

module Ganeti.Prelude (

    -- * Standard types, classes and related functions

    -- ** Basic data types
    Bool(False, True),
    (&&), (||), not, otherwise,

    Maybe(Nothing, Just),
    maybe,

    Either(Left, Right),
    either,

    Ordering(LT, EQ, GT),
    Char, String,

    -- *** Tuples
    fst, snd, curry, uncurry,

    -- ** Basic type classes
    Eq((==), (/=)),
    Ord(compare, (<), (<=), (>=), (>), max, min),
    Enum(succ, pred, toEnum, fromEnum, enumFrom, enumFromThen,
         enumFromTo, enumFromThenTo),
    Bounded(minBound, maxBound),

    -- ** Numbers

    -- *** Numeric types
    Int, Integer, Float, Double,
    Rational, Word,

    -- *** Numeric type classes
    Num((+), (-), (*), negate, abs, signum, fromInteger),
    Real(toRational),
    Integral(quot, rem, div, mod, quotRem, divMod, toInteger),
    Fractional((/), recip, fromRational),
    Floating(pi, exp, log, sqrt, (**), logBase, sin, cos, tan,
             asin, acos, atan, sinh, cosh, tanh, asinh, acosh, atanh),
    RealFrac(properFraction, truncate, round, ceiling, floor),
    RealFloat(floatRadix, floatDigits, floatRange, decodeFloat,
              encodeFloat, exponent, significand, scaleFloat, isNaN,
              isInfinite, isDenormalized, isIEEE, isNegativeZero, atan2),

    -- *** Numeric functions
    subtract, even, odd, gcd, lcm, (^), (^^),
    fromIntegral, realToFrac,

    -- ** Monoids
    Monoid(mempty, mappend, mconcat),

    -- ** Monads and functors
    Functor(fmap, (<$)), (<$>),
    Applicative(pure, (<*>), (*>), (<*)),
    Monad((>>=), (>>), return, fail),
    mapM_, sequence_, (=<<),

#if MIN_VERSION_base(4,8,0)
    -- ** Folds and traversals
    Foldable(elem,      -- :: (Foldable t, Eq a) => a -> t a -> Bool
             -- fold,   -- :: Monoid m => t m -> m
             foldMap,   -- :: Monoid m => (a -> m) -> t a -> m
             foldr,     -- :: (a -> b -> b) -> b -> t a -> b
             -- foldr', -- :: (a -> b -> b) -> b -> t a -> b
             foldl,     -- :: (b -> a -> b) -> b -> t a -> b
             -- foldl', -- :: (b -> a -> b) -> b -> t a -> b
             foldr1,    -- :: (a -> a -> a) -> t a -> a
             foldl1,    -- :: (a -> a -> a) -> t a -> a
             maximum,   -- :: (Foldable t, Ord a) => t a -> a
             minimum,   -- :: (Foldable t, Ord a) => t a -> a
             product,   -- :: (Foldable t, Num a) => t a -> a
             sum),      -- :: Num a => t a -> a
             -- toList) -- :: Foldable t => t a -> [a]
#else
    Foldable(foldMap,
             foldr,
             foldl,
             foldr1,
             foldl1),
    elem,
    maximum,
    minimum,
    product,
    sum,
#endif

    Traversable(traverse, sequenceA, mapM, sequence),

    -- ** Miscellaneous functions
    id, const, (.), flip, ($), until,
    asTypeOf, error, undefined,
    seq, ($!),

    -- * List operations
    map, (++), filter,
    head, last, tail, init, null, length, (!!),
    reverse,
    -- *** Special folds
    and, or, any, all,
    concat, concatMap,
    -- ** Building lists
    -- *** Scans
    scanl, scanl1, scanr, scanr1,
    -- *** Infinite lists
    iterate, repeat, replicate, cycle,
    -- ** Sublists
    take, drop, splitAt, takeWhile, dropWhile, span, break,
    -- ** Searching lists
    notElem, lookup,
    -- ** Zipping and unzipping lists
    zip, zip3, zipWith, zipWith3, unzip, unzip3,
    -- ** Functions on strings
    lines, words, unlines, unwords,

    -- * Converting to and from @String@
    -- ** Converting to @String@
    ShowS,
    Show(showsPrec, showList, show),
    shows,
    showChar, showString, showParen,
    -- ** Converting from @String@
    ReadS,
    Read(readsPrec, readList),
    reads, readParen, read, lex,

    -- * Basic Input and output
    IO,
    -- ** Simple I\/O operations
    -- All I/O functions defined here are character oriented.  The
    -- treatment of the newline character will vary on different systems.
    -- For example, two characters of input, return and linefeed, may
    -- read as a single newline character.  These functions cannot be
    -- used portably for binary I/O.
    -- *** Output functions
    putChar,
    putStr, putStrLn, print,
    -- *** Input functions
    getChar,
    getLine, getContents, interact,
    -- *** Files
    FilePath,
    readFile, writeFile, appendFile, readIO, readLn,
    -- ** Exception handling in the I\/O monad
    IOError, ioError, userError,

  ) where

#if MIN_VERSION_base(4,8,0)
import Prelude
#else
import Prelude hiding   ( elem, maximum, minimum, product, sum )
import Data.Foldable    ( Foldable(..), elem, maximum, minimum, product, sum )
import Data.Traversable ( Traversable(..) )
import Control.Applicative
import Data.Monoid
import Data.Word
#endif
