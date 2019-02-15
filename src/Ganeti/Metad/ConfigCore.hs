{-# LANGUAGE TupleSections, TemplateHaskell, CPP, UndecidableInstances,
    MultiParamTypeClasses, TypeFamilies, GeneralizedNewtypeDeriving #-}
{-| Functions of the metadata daemon exported for RPC

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
module Ganeti.Metad.ConfigCore where

import Control.Applicative
import Control.Concurrent.MVar.Lifted
import Control.Monad.Base
import Control.Monad.IO.Class
import Control.Monad.Reader
import Control.Monad.Trans.Control
import Language.Haskell.TH (Name)
import qualified Text.JSON as J

import Ganeti.BasicTypes
import Ganeti.Errors
import qualified Ganeti.JSON as J
import Ganeti.Logging as L
import Ganeti.Metad.Config as Config
import Ganeti.Metad.Types (InstanceParams)

-- * The monad in which all the Metad functions execute

data MetadHandle = MetadHandle
  { mhInstParams :: MVar InstanceParams
  }

-- | A type alias for easier referring to the actual content of the monad
-- when implementing its instances.
type MetadMonadIntType = ReaderT MetadHandle IO

-- | The internal part of the monad without error handling.
newtype MetadMonadInt a = MetadMonadInt
  { getMetadMonadInt :: MetadMonadIntType a }
  deriving ( Functor, Applicative, Monad, MonadIO, MonadBase IO
           , L.MonadLog )

instance MonadBaseControl IO MetadMonadInt where
#if MIN_VERSION_monad_control(1,0,0)
-- Needs Undecidable instances
  type StM MetadMonadInt b = StM MetadMonadIntType b
  liftBaseWith f = MetadMonadInt . liftBaseWith
                   $ \r -> f (r . getMetadMonadInt)
  restoreM = MetadMonadInt . restoreM
#else
  newtype StM MetadMonadInt b = StMMetadMonadInt
    { runStMMetadMonadInt :: StM MetadMonadIntType b }
  liftBaseWith f = MetadMonadInt . liftBaseWith
                   $ \r -> f (liftM StMMetadMonadInt . r . getMetadMonadInt)
  restoreM = MetadMonadInt . restoreM . runStMMetadMonadInt
#endif

-- | Runs the internal part of the MetadMonad monad on a given daemon
-- handle.
runMetadMonadInt :: MetadMonadInt a -> MetadHandle -> IO a
runMetadMonadInt (MetadMonadInt k) = runReaderT k

-- | The complete monad with error handling.
type MetadMonad = ResultT GanetiException MetadMonadInt

-- * Basic functions in the monad

metadHandle :: MetadMonad MetadHandle
metadHandle = lift . MetadMonadInt $ ask

instParams :: MetadMonad InstanceParams
instParams = readMVar . mhInstParams =<< metadHandle

modifyInstParams :: (InstanceParams -> MetadMonad (InstanceParams, a))
                 -> MetadMonad a
modifyInstParams f = do
  h <- metadHandle
  modifyMVar (mhInstParams h) f

-- * Functions available to the RPC module

-- Just a debugging function
echo :: String -> MetadMonad String
echo = return

-- | Update the configuration with the received instance parameters.
updateConfig :: J.JSValue -> MetadMonad ()
updateConfig input = do
  (name, m'instanceParams) <- J.fromJResultE "Could not get instance parameters"
                              $ Config.getInstanceParams input
  case m'instanceParams of
    Nothing -> L.logInfo $ "No communication NIC for instance " ++ name
                           ++ ", skipping"
    Just instanceParams -> do
      cfg' <- modifyInstParams $ \cfg ->
        let cfg' = mergeConfig cfg instanceParams
         in return (cfg', cfg')
      L.logInfo $
        "Updated instance " ++ name ++ " configuration"
      L.logDebug $ "Instance configuration: " ++ show cfg'

-- * The list of all functions exported to RPC.

exportedFunctions :: [Name]
exportedFunctions = [ 'echo
                    , 'updateConfig
                    ]
