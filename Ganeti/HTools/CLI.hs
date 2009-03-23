{-| Implementation of command-line functions.

This module holds the common cli-related functions for the binaries,
separated into this module since Utils.hs is used in many other places
and this is more IO oriented.

-}

module Ganeti.HTools.CLI
    (
      parseOpts
    , showVersion
    ) where

import System.Console.GetOpt
import System.IO
import System.Info
import System
import Monad
import Text.Printf (printf)
import qualified Data.Version

import qualified Ganeti.HTools.Version as Version(version)

-- | Command line parser, using the 'options' structure.
parseOpts :: [String]            -- ^ The command line arguments
          -> String              -- ^ The program name
          -> [OptDescr (b -> b)] -- ^ The supported command line options
          -> b                   -- ^ The default options record
          -> (b -> Bool)         -- ^ The function which given the options
                                 -- tells us whether we need to show help
          -> IO (b, [String])    -- ^ The resulting options a leftover
                                 -- arguments
parseOpts argv progname options defaultOptions fn =
    case getOpt Permute options argv of
      (o, n, []) ->
          do
            let resu@(po, _) = (foldl (flip id) defaultOptions o, n)
            when (fn po) $ do
              putStr $ usageInfo header options
              exitWith ExitSuccess
            return resu
      (_, _, errs) ->
          ioError (userError (concat errs ++ usageInfo header options))
      where header = printf "%s %s\nUsage: %s [OPTION...]"
                     progname Version.version progname


-- | Return a version string for the program
showVersion :: String -- ^ The program name
            -> String -- ^ The formatted version and other information data
showVersion name =
    printf "%s %s\ncompiled with %s %s\nrunning on %s %s\n"
           name Version.version
           compilerName (Data.Version.showVersion compilerVersion)
           os arch
