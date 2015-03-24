{-# LANGUAGE FlexibleInstances #-}
{-# LANGUAGE FlexibleContexts #-}
{-# LANGUAGE MultiParamTypeClasses #-}
{-# LANGUAGE TypeFamilies #-}
{-# LANGUAGE DeriveFunctor #-}
{-# LANGUAGE UndecidableInstances #-}
{-# LANGUAGE CPP #-}

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

module Ganeti.BasicTypes
  ( GenericResult(..)
  , genericResult
  , Result
  , ResultT(..)
  , mkResultT
  , withError
  , withErrorT
  , toError
  , toErrorBase
  , toErrorStr
  , tryError
  , Error(..) -- re-export from Control.Monad.Error
  , MonadIO(..) -- re-export from Control.Monad.IO.Class
  , isOk
  , isBad
  , justOk
  , justBad
  , eitherToResult
  , isLeft
  , isRight
  , annotateResult
  , annotateError
  , failError
  , catchErrorT
  , handleErrorT
  , orElse
  , iterateOk
  , select
  , runListHead
  , LookupResult(..)
  , MatchPriority(..)
  , lookupName
  , goodLookupResult
  , goodMatchPriority
  , prefixMatch
  , compareNameComponent
  , ListSet(..)
  , emptyListSet
  ) where

import Control.Applicative
import Control.Exception (try)
import Control.Monad
import Control.Monad.Base
import Control.Monad.Error.Class
import Control.Monad.Trans
import Control.Monad.Trans.Control
import Data.Function
import Data.List
import Data.Maybe
import Data.Monoid
import Data.Set (Set)
import qualified Data.Set as Set (empty)
import Text.JSON (JSON)
import qualified Text.JSON as JSON (readJSON, showJSON)

-- Remove after we require >= 1.8.58
-- See: https://github.com/ndmitchell/hlint/issues/24
{-# ANN module "HLint: ignore Unused LANGUAGE pragma" #-}

-- | Generic monad for our error handling mechanisms.
data GenericResult a b
  = Bad a
  | Ok b
    deriving (Show, Eq)

-- | Sum type structure of GenericResult.
genericResult :: (a -> c) -> (b -> c) -> GenericResult a b -> c
genericResult f _ (Bad a) = f a
genericResult _ g (Ok b) = g b
{-# INLINE genericResult #-}

-- | Type alias for a string Result.
type Result = GenericResult String

-- | 'Monad' instance for 'GenericResult'.
instance (Error a) => Monad (GenericResult a) where
  (>>=) (Bad x) _ = Bad x
  (>>=) (Ok x) fn = fn x
  return = Ok
  fail   = Bad . strMsg

instance Functor (GenericResult a) where
  fmap _ (Bad msg) = Bad msg
  fmap fn (Ok val) = Ok (fn val)

instance (Error a, Monoid a) => MonadPlus (GenericResult a) where
  mzero = Bad $ strMsg "zero Result when used as MonadPlus"
  -- for mplus, when we 'add' two Bad values, we concatenate their
  -- error descriptions
  (Bad x) `mplus` (Bad y) = Bad (x `mappend` strMsg "; " `mappend` y)
  (Bad _) `mplus` x = x
  x@(Ok _) `mplus` _ = x

instance (Error a) => MonadError a (GenericResult a) where
  throwError = Bad
  {-# INLINE throwError #-}
  catchError x h = genericResult h (const x) x
  {-# INLINE catchError #-}

instance Applicative (GenericResult a) where
  pure = Ok
  (Bad f) <*> _       = Bad f
  _       <*> (Bad x) = Bad x
  (Ok f)  <*> (Ok x)  = Ok $ f x

instance (Error a, Monoid a) => Alternative (GenericResult a) where
  empty = mzero
  (<|>) = mplus

-- | This is a monad transformation for Result. It's implementation is
-- based on the implementations of MaybeT and ErrorT.
--
-- 'ResultT' is very similar to @ErrorT@, but with one subtle difference:
-- If 'mplus' combines two failing operations, errors of both of them
-- are combined.
newtype ResultT a m b = ResultT {runResultT :: m (GenericResult a b)}
  deriving (Functor)

-- | Eliminates a 'ResultT' value given appropriate continuations
elimResultT :: (Monad m)
            => (a -> ResultT a' m b')
            -> (b -> ResultT a' m b')
            -> ResultT a m b
            -> ResultT a' m b'
elimResultT l r = ResultT . (runResultT . result <=< runResultT)
  where
    result (Ok x)   = r x
    result (Bad e)  = l e
{-# INLINE elimResultT #-}

instance (Applicative m, Monad m, Error a) => Applicative (ResultT a m) where
  pure = return
  (<*>) = ap

instance (Monad m, Error a) => Monad (ResultT a m) where
  fail err = ResultT (return . Bad $ strMsg err)
  return   = lift . return
  (>>=)    = flip (elimResultT throwError)

instance (Monad m, Error a) => MonadError a (ResultT a m) where
  throwError = ResultT . return . Bad
  catchError = catchErrorT

instance MonadTrans (ResultT a) where
  lift = ResultT . liftM Ok

-- | The instance catches any 'IOError' using 'try' and converts it into an
-- error message using 'strMsg'.
--
-- This way, monadic code within 'ResultT' that uses solely 'liftIO' to
-- include 'IO' actions ensures that all IO exceptions are handled.
--
-- Other exceptions (see instances of 'Exception') are not currently handled.
-- This might be revised in the future.
instance (MonadIO m, Error a) => MonadIO (ResultT a m) where
  liftIO = ResultT . liftIO
                   . liftM (either (failError . show) return)
                   . (try :: IO a -> IO (Either IOError a))

instance (MonadBase IO m, Error a) => MonadBase IO (ResultT a m) where
  liftBase = ResultT . liftBase
                   . liftM (either (failError . show) return)
                   . (try :: IO a -> IO (Either IOError a))

instance (Error a) => MonadTransControl (ResultT a) where
#if MIN_VERSION_monad_control(1,0,0)
-- Needs Undecidable instances
  type StT (ResultT a) b = GenericResult a b
  liftWith f = ResultT . liftM return $ f runResultT
  restoreT = ResultT
#else
  newtype StT (ResultT a) b = StResultT { runStResultT :: GenericResult a b }
  liftWith f = ResultT . liftM return $ f (liftM StResultT . runResultT)
  restoreT = ResultT . liftM runStResultT
#endif
  {-# INLINE liftWith #-}
  {-# INLINE restoreT #-}

instance (Error a, MonadBaseControl IO m)
         => MonadBaseControl IO (ResultT a m) where
#if MIN_VERSION_monad_control(1,0,0)
-- Needs Undecidable instances
  type StM (ResultT a m) b
    = ComposeSt (ResultT a) m b
  liftBaseWith = defaultLiftBaseWith
  restoreM = defaultRestoreM
#else
  newtype StM (ResultT a m) b
    = StMResultT { runStMResultT :: ComposeSt (ResultT a) m b }
  liftBaseWith = defaultLiftBaseWith StMResultT
  restoreM = defaultRestoreM runStMResultT
#endif
  {-# INLINE liftBaseWith #-}
  {-# INLINE restoreM #-}

instance (Monad m, Error a, Monoid a) => MonadPlus (ResultT a m) where
  mzero = ResultT $ return mzero
  -- Ensure that 'y' isn't run if 'x' contains a value. This makes it a bit
  -- more complicated than 'mplus' of 'GenericResult'.
  mplus x y = elimResultT combine return x
    where combine x' = ResultT $ liftM (mplus (Bad x')) (runResultT y)

instance (Alternative m, Monad m, Error a, Monoid a)
         => Alternative (ResultT a m) where
  empty = mzero
  (<|>) = mplus

-- | Changes the error message of a result value, if present.
-- Note that since 'GenericResult' is also a 'MonadError', this function
-- is a generalization of
-- @(Error e') => (e' -> e) -> GenericResult e' a -> GenericResult e a@
withError :: (MonadError e m) => (e' -> e) -> GenericResult e' a -> m a
withError f = genericResult (throwError . f) return

-- | Changes the error message of a @ResultT@ value, if present.
withErrorT :: (Monad m, Error e)
           => (e' -> e) -> ResultT e' m a -> ResultT e m a
withErrorT f = ResultT . liftM (withError f) . runResultT

-- | Lift a 'Result' value to any 'MonadError'. Since 'ResultT' is itself its
-- instance, it's a generalization of
-- @Monad m => GenericResult a b -> ResultT a m b@.
toError :: (MonadError e m) => GenericResult e a -> m a
toError = genericResult throwError return
{-# INLINE toError #-}

-- | Lift a 'ResultT' value into any 'MonadError' with the same base monad.
toErrorBase :: (MonadBase b m, MonadError e m) => ResultT e b a -> m a
toErrorBase = (toError =<<) . liftBase . runResultT
{-# INLINE toErrorBase #-}

-- | An alias for @withError strMsg@, which is often used to lift a pure error
-- to a monad stack. See also 'annotateResult'.
toErrorStr :: (MonadError e m, Error e) => Result a -> m a
toErrorStr = withError strMsg

-- | Run a given computation and if an error occurs, return it as `Left` of
-- `Either`.
-- This is a generalized version of 'try'.
tryError :: (MonadError e m) => m a -> m (Either e a)
tryError = flip catchError (return . Left) . liftM Right
{-# INLINE tryError #-}

-- | Converts a monadic result with a 'String' message into
-- a 'ResultT' with an arbitrary 'Error'.
--
-- Expects that the given action has already taken care of any possible
-- errors. In particular, if applied on @IO (Result a)@, any exceptions
-- should be handled by the given action.
--
-- See also 'toErrorStr'.
mkResultT :: (Monad m, Error e) => m (Result a) -> ResultT e m a
mkResultT = ResultT . liftM toErrorStr

-- | Simple checker for whether a 'GenericResult' is OK.
isOk :: GenericResult a b -> Bool
isOk (Ok _) = True
isOk _      = False

-- | Simple checker for whether a 'GenericResult' is a failure.
isBad :: GenericResult a b -> Bool
isBad = not . isOk

-- | Simple filter returning only OK values of GenericResult
justOk :: [GenericResult a b] -> [b]
justOk = mapMaybe (genericResult (const Nothing) Just)

-- | Simple filter returning only Bad values of GenericResult
justBad :: [GenericResult a b] -> [a]
justBad = mapMaybe (genericResult Just (const Nothing))

-- | Converter from Either to 'GenericResult'.
eitherToResult :: Either a b -> GenericResult a b
eitherToResult (Left  s) = Bad s
eitherToResult (Right v) = Ok  v

-- | Check if an either is Left. Equivalent to isLeft from Data.Either
-- version 4.7.0.0 or higher.
isLeft :: Either a b -> Bool
isLeft (Left _) = True
isLeft _        = False

-- | Check if an either is Right. Equivalent to isRight from Data.Either
-- version 4.7.0.0 or higher.
isRight :: Either a b -> Bool
isRight = not . isLeft

-- | Annotate an error with an ownership information, lifting it to a
-- 'MonadError'. Since 'Result' is an instance of 'MonadError' itself,
-- it's a generalization of type @String -> Result a -> Result a@.
-- See also 'toErrorStr'.
annotateResult :: (MonadError e m, Error e) => String -> Result a -> m a
annotateResult owner = toErrorStr . annotateError owner

-- | Annotate an error with an ownership information inside a 'MonadError'.
-- See also 'annotateResult'.
annotateError :: (MonadError e m, Error e, Monoid e) => String -> m a -> m a
annotateError owner =
  flip catchError (throwError . mappend (strMsg $ owner ++ ": "))
{-# INLINE annotateError #-}

-- | Throws a 'String' message as an error in a 'MonadError'.
-- This is a generalization of 'Bad'.
-- It's similar to 'fail', but works within a 'MonadError', avoiding the
-- unsafe nature of 'fail'.
failError :: (MonadError e m, Error e) => String -> m a
failError = throwError . strMsg

-- | A synonym for @flip@ 'catchErrorT'.
handleErrorT :: (Monad m, Error e)
             => (e' -> ResultT e m a) -> ResultT e' m a -> ResultT e m a
handleErrorT handler = elimResultT handler return
{-# INLINE handleErrorT #-}

-- | Catches an error in a @ResultT@ value. This is similar to 'catchError',
-- but in addition allows to change the error type.
catchErrorT :: (Monad m, Error e)
            => ResultT e' m a -> (e' -> ResultT e m a) -> ResultT e m a
catchErrorT = flip handleErrorT
{-# INLINE catchErrorT #-}

-- | If the first computation fails, run the second one.
-- Unlike 'mplus' instance for 'ResultT', this doesn't require
-- the 'Monoid' constrait.
orElse :: (MonadError e m) => m a -> m a -> m a
orElse x y = catchError x (const y)

-- | Iterate while Ok.
iterateOk :: (a -> GenericResult b a) -> a -> [a]
iterateOk f a = genericResult (const []) ((:) a . iterateOk f) (f a)

-- * Misc functionality

-- | Return the first result with a True condition, or the default otherwise.
select :: a            -- ^ default result
       -> [(Bool, a)]  -- ^ list of \"condition, result\"
       -> a            -- ^ first result which has a True condition, or default
select def = maybe def snd . find fst

-- | Apply a function to the first element of a list, return the default
-- value, if the list is empty. This is just a convenient combination of
-- maybe and listToMaybe.
runListHead :: a -> (b -> a) -> [b] -> a
runListHead a f = maybe a f . listToMaybe

-- * Lookup of partial names functionality

-- | The priority of a match in a lookup result.
data MatchPriority = ExactMatch
                   | MultipleMatch
                   | PartialMatch
                   | FailMatch
                   deriving (Show, Enum, Eq, Ord)

-- | The result of a name lookup in a list.
data LookupResult = LookupResult
  { lrMatchPriority :: MatchPriority -- ^ The result type
  -- | Matching value (for ExactMatch, PartialMatch), Lookup string otherwise
  , lrContent :: String
  } deriving (Show)

-- | Lookup results have an absolute preference ordering.
instance Eq LookupResult where
  (==) = (==) `on` lrMatchPriority

instance Ord LookupResult where
  compare = compare `on` lrMatchPriority

-- | Check for prefix matches in names.
-- Implemented in Ganeti core utils.text.MatchNameComponent
-- as the regexp r"^%s(\..*)?$" % re.escape(key)
prefixMatch :: String  -- ^ Lookup
            -> String  -- ^ Full name
            -> Bool    -- ^ Whether there is a prefix match
prefixMatch = isPrefixOf . (++ ".")

-- | Is the lookup priority a "good" one?
goodMatchPriority :: MatchPriority -> Bool
goodMatchPriority ExactMatch = True
goodMatchPriority PartialMatch = True
goodMatchPriority _ = False

-- | Is the lookup result an actual match?
goodLookupResult :: LookupResult -> Bool
goodLookupResult = goodMatchPriority . lrMatchPriority

-- | Compares a canonical name and a lookup string.
compareNameComponent :: String        -- ^ Canonical (target) name
                     -> String        -- ^ Partial (lookup) name
                     -> LookupResult  -- ^ Result of the lookup
compareNameComponent cnl lkp =
  select (LookupResult FailMatch lkp)
  [ (cnl == lkp          , LookupResult ExactMatch cnl)
  , (prefixMatch lkp cnl , LookupResult PartialMatch cnl)
  ]

-- | Lookup a string and choose the best result.
chooseLookupResult :: String       -- ^ Lookup key
                   -> String       -- ^ String to compare to the lookup key
                   -> LookupResult -- ^ Previous result
                   -> LookupResult -- ^ New result
chooseLookupResult lkp cstr old =
  -- default: use class order to pick the minimum result
  select (min new old)
  -- special cases:
  -- short circuit if the new result is an exact match
  [ (lrMatchPriority new == ExactMatch, new)
  -- if both are partial matches generate a multiple match
  , (partial2, LookupResult MultipleMatch lkp)
  ] where new = compareNameComponent cstr lkp
          partial2 = all ((PartialMatch==) . lrMatchPriority) [old, new]

-- | Find the canonical name for a lookup string in a list of names.
lookupName :: [String]      -- ^ List of keys
           -> String        -- ^ Lookup string
           -> LookupResult  -- ^ Result of the lookup
lookupName l s = foldr (chooseLookupResult s)
                       (LookupResult FailMatch s) l

-- | Wrapper for a Haskell 'Set'
--
-- This type wraps a 'Set' and it is used in the Haskell to Python
-- opcode generation to transform a Haskell 'Set' into a Python 'list'
-- without duplicate elements.
newtype ListSet a = ListSet { unListSet :: Set a }
  deriving (Eq, Show, Ord)

instance (Ord a, JSON a) => JSON (ListSet a) where
  showJSON = JSON.showJSON . unListSet
  readJSON = liftM ListSet . JSON.readJSON

emptyListSet :: ListSet a
emptyListSet = ListSet Set.empty
