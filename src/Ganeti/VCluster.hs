{-| Utilities for virtual clusters.

-}

{-

Copyright (C) 2014 Google Inc.

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
