module Main where

import Control.Applicative
import qualified Data.Set as Set
import qualified Distribution.Simple.Build.Macros as Macros
import Distribution.Simple.Configure (maybeGetPersistBuildConfig)
import Distribution.Simple.LocalBuildInfo (externalPackageDeps)
import Distribution.PackageDescription (packageDescription)
import Distribution.PackageDescription.Parse (readPackageDescription)
import Distribution.Text (display)
import Distribution.Verbosity (normal)
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
  pkgDesc <- packageDescription <$> readPackageDescription normal cabalPath

  -- Read the setup-config.
  m'conf <- maybeGetPersistBuildConfig "dist"
  case m'conf of
    Nothing -> error "could not read dist/setup-config"
    Just conf -> do

      -- Write package dependencies.
      let deps = map (display . fst) $ externalPackageDeps conf
      writeFile depsPath (unwords $ map ("-package-id " ++) deps)

      -- Write package MIN_VERSION_* macros.
      writeFile macrosPath $ Macros.generate pkgDesc conf
