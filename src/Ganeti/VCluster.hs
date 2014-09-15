{-| Utilities for virtual clusters.

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

module Ganeti.VCluster
  ( makeVirtualPath
  ) where

import Control.Monad (liftM)
import Data.Set (member)
import System.Posix.Env (getEnv)
import System.FilePath.Posix

import Ganeti.ConstantUtils (unFrozenSet)
import Ganeti.Constants

getRootDirectory :: IO (Maybe FilePath)
getRootDirectory = fmap normalise `liftM` getEnv vClusterRootdirEnvname

-- | Pure computation of the virtual path from the original path
-- and the vcluster root
virtualPath :: FilePath -> FilePath -> FilePath
virtualPath fpath root =
  let relpath = makeRelative root fpath
  in if member fpath (unFrozenSet vClusterVpathWhitelist)
       then fpath
       else vClusterVirtPathPrefix </> relpath

-- | Given a path, make it a virtual one, if in a vcluster environment.
-- Otherwise, return unchanged.
makeVirtualPath :: FilePath -> IO FilePath
makeVirtualPath fpath = maybe fpath (virtualPath fpath) `liftM` getRootDirectory
