module Main where

import Control.Applicative
import qualified Data.Set as Set
import qualified Distribution.Simple.Build.Macros as Macros
import Distribution.Simple.Configure (maybeGetPersistBuildConfig)
import Distribution.Simple.LocalBuildInfo (externalPackageDeps)
import Distribution.PackageDescription (packageDescription)
import Distribution.PackageDescription.Parsec (readGenericPackageDescription)
import Distribution.Text (display)
import Distribution.Verbosity (normal)
import qualified Distribution.Types.LocalBuildInfo as LocalBuildInfo
import qualified Distribution.Compat.Graph as Graph
import System.Environment (getArgs)


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
  m'conf <- maybeGetPersistBuildConfig "dist"
  case m'conf of
    Nothing -> error "could not read dist/setup-config"
    Just conf -> do

      -- Write package dependencies.
      let deps = map (display . fst) $ externalPackageDeps conf
      writeFile depsPath (unwords $ map ("-package-id " ++) deps)

      -- Write package MIN_VERSION_* macros.
      let cid = LocalBuildInfo.localUnitId conf
      let clbi' = Graph.lookup cid $ LocalBuildInfo.componentGraph conf
      case clbi' of
        Nothing -> error "Unable to read componentLocalBuildInfo for the library"
        Just clbi -> do
          writeFile macrosPath $ Macros.generate pkgDesc conf clbi
