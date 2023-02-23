{-# LANGUAGE CPP #-}
module Main where

import Control.Applicative
import qualified Data.Set as Set
import qualified Distribution.Simple.Build.Macros as Macros
import Distribution.Simple.Configure (getPersistBuildConfig)
import Distribution.Simple.LocalBuildInfo (externalPackageDeps)
import Distribution.PackageDescription (packageDescription)

-- MIN_VERSION_* macros are automatically defined by GHC only since 7.11, see
-- https://ghc.haskell.org/trac/ghc/ticket/10970
--
-- For the rest of the source this is fine, because the MIN_VERSION_* macros
-- are defined by cabal next, but at this stage cabal can not run (yet). So, we
-- rely on the __GLASGOW_HASKELL__ macro which is always present to define the
-- MIN_VERSION_* macros which always return false.
#if __GLASGOW_HASKELL__ < 711
#ifndef MIN_VERSION_Cabal
#define MIN_VERSION_Cabal(x,y,z) 0
#endif
#endif

-- Common Cabal 2.x dependencies
#if MIN_VERSION_Cabal(2,0,0)
import qualified Distribution.Types.LocalBuildInfo as LocalBuildInfo
import qualified Distribution.Compat.Graph as Graph
#endif

#if MIN_VERSION_Cabal(2,2,0)
import Distribution.PackageDescription.Parsec (readGenericPackageDescription)
#elif MIN_VERSION_Cabal(2,0,0)
import Distribution.PackageDescription.Parse (readGenericPackageDescription)
#else
import Distribution.PackageDescription.Parse (readPackageDescription)
#endif

import Distribution.Text (display)
import Distribution.Verbosity (normal)
import System.Environment (getArgs)

#if !MIN_VERSION_Cabal(2,0,0)
readGenericPackageDescription = readPackageDescription
#endif

main :: IO ()
main = do
  -- Get paths from program arguments.
  (cabalPath, depsPath, macrosPath) <- do
    args <- getArgs
    case args of
      [c, d, m] -> return (c, d, m)
      _         -> error "Expected 3 arguments: cabalPath depsPath macrosPath"

  -- Read the cabal file.
  pkgDesc <- packageDescription <$> readGenericPackageDescription normal cabalPath

  -- Read the setup-config.
  conf <- getPersistBuildConfig "dist"

  -- Write package dependencies.
  let deps = map (display . fst) $ externalPackageDeps conf
  writeFile depsPath (unwords $ map ("-package-id " ++) deps)

  -- Write package MIN_VERSION_* macros.
#if MIN_VERSION_Cabal(2,0,0)
  let cid = LocalBuildInfo.localUnitId conf
  let clbi' = Graph.lookup cid $ LocalBuildInfo.componentGraph conf
  case clbi' of
     Nothing -> error "Unable to read componentLocalBuildInfo for the library"
     Just clbi -> do
      writeFile macrosPath $ Macros.generate pkgDesc conf clbi
#else
  writeFile macrosPath $ Macros.generate pkgDesc conf
#endif
