{-# LANGUAGE CPP #-}
module Main where

import Control.Applicative
import qualified Data.Set as Set
import qualified Distribution.Simple.Build.Macros as Macros
import Distribution.Simple.Configure (getPersistBuildConfig)
#if MIN_VERSION_Cabal(3,0,0)
import Distribution.Types.UnitId (UnitId)
import Distribution.Types.MungedPackageId (MungedPackageId)
import Distribution.Types.ComponentLocalBuildInfo (componentPackageDeps, componentUnitId)
import Data.List (nub)
#else
import Distribution.Simple.LocalBuildInfo (externalPackageDeps)
#endif
import Distribution.PackageDescription (packageDescription)

-- Common Cabal 2.x dependencies
#if MIN_VERSION_Cabal(2,0,0)
import qualified Distribution.Types.LocalBuildInfo as LocalBuildInfo
import qualified Distribution.Compat.Graph as Graph
#endif

#if MIN_VERSION_Cabal(3,8,0)
import Distribution.Simple.PackageDescription (readGenericPackageDescription)
#elif MIN_VERSION_Cabal(2,2,0)
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

#if MIN_VERSION_Cabal(3,0,0)
generate = Macros.generateCabalMacrosHeader
#else
generate = Macros.generate
#endif

#if MIN_VERSION_Cabal(3,0,0)
externalPackageDeps :: LocalBuildInfo.LocalBuildInfo -> [(UnitId, MungedPackageId)]
externalPackageDeps lbi =
    nub [ (ipkgid, pkgid)
        | clbi            <- clbis
        , (ipkgid, pkgid) <- componentPackageDeps clbi
        , not (internal ipkgid) ]
  where
    -- True if this dependency is an internal one (depends on the library
    -- defined in the same package).
    internal ipkgid = any ((==ipkgid) . componentUnitId) clbis
    clbis = Graph.toList $ LocalBuildInfo.componentGraph lbi
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
      writeFile macrosPath $ generate pkgDesc conf clbi
#else
  writeFile macrosPath $ generate pkgDesc conf
#endif
