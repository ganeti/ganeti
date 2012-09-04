{-| Base common functionality.

This module holds common functionality shared across Ganeti daemons,
HTools and any other programs.

-}

{-

Copyright (C) 2009, 2010, 2011, 2012 Google Inc.

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

module Ganeti.Common
  ( GenericOptType
  , StandardOptions(..)
  , oShowHelp
  , oShowVer
  , usageHelp
  , versionInfo
  , reqWithConversion
  , parseYesNo
  , parseOpts
  , parseOptsInner
  ) where

import Control.Monad (foldM)
import qualified Data.Version
import System.Console.GetOpt
import System.Exit
import System.Info
import System.IO
import Text.Printf (printf)

import Ganeti.BasicTypes
import qualified Ganeti.Version as Version (version)

-- | Abrreviation for the option type.
type GenericOptType a = OptDescr (a -> Result a)

-- | Type class for options which support help and version.
class StandardOptions a where
  helpRequested :: a -> Bool
  verRequested  :: a -> Bool
  requestHelp   :: a -> a
  requestVer    :: a -> a

-- | Options to request help output.
oShowHelp :: (StandardOptions a) => GenericOptType a
oShowHelp = Option "h" ["help"] (NoArg (Ok . requestHelp))
            "show help"

oShowVer :: (StandardOptions a) => GenericOptType a
oShowVer = Option "V" ["version"] (NoArg (Ok . requestVer))
           "show the version of the program"

-- | Usage info.
usageHelp :: String -> [GenericOptType a] -> String
usageHelp progname =
  usageInfo (printf "%s %s\nUsage: %s [OPTION...]"
             progname Version.version progname)

-- | Show the program version info.
versionInfo :: String -> String
versionInfo progname =
  printf "%s %s\ncompiled with %s %s\nrunning on %s %s\n"
         progname Version.version compilerName
         (Data.Version.showVersion compilerVersion)
         os arch

-- | Helper for parsing a yes\/no command line flag.
parseYesNo :: Bool         -- ^ Default value (when we get a @Nothing@)
           -> Maybe String -- ^ Parameter value
           -> Result Bool  -- ^ Resulting boolean value
parseYesNo v Nothing      = return v
parseYesNo _ (Just "yes") = return True
parseYesNo _ (Just "no")  = return False
parseYesNo _ (Just s)     = fail ("Invalid choice '" ++ s ++
                                  "', pass one of 'yes' or 'no'")

-- | Helper function for required arguments which need to be converted
-- as opposed to stored just as string.
reqWithConversion :: (String -> Result a)
                  -> (a -> b -> Result b)
                  -> String
                  -> ArgDescr (b -> Result b)
reqWithConversion conversion_fn updater_fn =
  ReqArg (\string_opt opts -> do
            parsed_value <- conversion_fn string_opt
            updater_fn parsed_value opts)

-- | Command line parser, using a generic 'Options' structure.
parseOpts :: (StandardOptions a) =>
             a                      -- ^ The default options
          -> [String]               -- ^ The command line arguments
          -> String                 -- ^ The program name
          -> [GenericOptType a]     -- ^ The supported command line options
          -> IO (a, [String])       -- ^ The resulting options and
                                    -- leftover arguments
parseOpts defaults argv progname options =
  case parseOptsInner defaults argv progname options of
    Left (code, msg) -> do
      hPutStr (if code == ExitSuccess then stdout else stderr) msg
      exitWith code
    Right result ->
      return result

-- | Inner parse options. The arguments are similar to 'parseOpts',
-- but it returns either a 'Left' composed of exit code and message,
-- or a 'Right' for the success case.
parseOptsInner :: (StandardOptions a) =>
                  a
               -> [String]
               -> String
               -> [GenericOptType a]
               -> Either (ExitCode, String) (a, [String])
parseOptsInner defaults argv progname options  =
  case getOpt Permute options argv of
    (opts, args, []) ->
      case foldM (flip id) defaults opts of
           Bad msg -> Left (ExitFailure 1,
                            "Error while parsing command line arguments:\n"
                            ++ msg ++ "\n")
           Ok parsed ->
             select (Right (parsed, args))
                 [ (helpRequested parsed,
                    Left (ExitSuccess, usageHelp progname options))
                 , (verRequested parsed,
                    Left (ExitSuccess, versionInfo progname))
                 ]
    (_, _, errs) ->
      Left (ExitFailure 2, "Command line error: "  ++ concat errs ++ "\n" ++
            usageHelp progname options)
