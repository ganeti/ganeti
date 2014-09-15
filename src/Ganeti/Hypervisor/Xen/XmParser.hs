{-# LANGUAGE OverloadedStrings #-}
{-| Parser for the output of the @xm list --long@ command of Xen

-}
{-

Copyright (C) 2013 Google Inc.
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
module Ganeti.Hypervisor.Xen.XmParser
  ( xmListParser
  , lispConfigParser
  , xmUptimeParser
  , uptimeLineParser
  ) where

import Control.Applicative
import Control.Monad
import qualified Data.Attoparsec.Combinator as AC
import qualified Data.Attoparsec.Text as A
import Data.Attoparsec.Text (Parser)
import Data.Char
import Data.List
import Data.Text (unpack)
import qualified Data.Map as Map

import Ganeti.BasicTypes
import Ganeti.Hypervisor.Xen.Types

-- | A parser for parsing generic config files written in the (LISP-like)
-- format that is the output of the @xm list --long@ command.
-- This parser only takes care of the syntactic parse, but does not care
-- about the semantics.
-- Note: parsing the double requires checking for the next character in order
-- to prevent string like "9a" to be recognized as the number 9.
lispConfigParser :: Parser LispConfig
lispConfigParser =
  A.skipSpace *>
    (   listConfigP
    <|> doubleP
    <|> stringP
    )
  <* A.skipSpace
    where listConfigP = LCList <$> (A.char '(' *> liftA2 (++)
            (many middleP)
            (((:[]) <$> finalP) <|> (rparen *> pure [])))
          doubleP = LCDouble <$> A.rational <* A.skipSpace <* A.endOfInput
          innerDoubleP = LCDouble <$> A.rational
          stringP = LCString . unpack <$> A.takeWhile1 (not . (\c -> isSpace c
            || c `elem` "()"))
          wspace = AC.many1 A.space
          rparen = A.skipSpace *> A.char ')'
          finalP =   listConfigP <* rparen
                 <|> innerDoubleP <* rparen
                 <|> stringP <* rparen
          middleP =   listConfigP <* wspace
                  <|> innerDoubleP <* wspace
                  <|> stringP <* wspace


-- | Find a configuration having the given string as its first element,
-- from a list of configurations.
findConf :: String -> [LispConfig] -> Result LispConfig
findConf key configs =
  case find (isNamed key) configs of
    (Just c) -> Ok c
    _ -> Bad "Configuration not found"

-- | Get the value of of a configuration having the given string as its
-- first element.
-- The value is the content of the configuration, discarding the name itself.
getValue :: (FromLispConfig a) => String -> [LispConfig] -> Result a
getValue key configs = findConf key configs >>= fromLispConfig

-- | Extract the values of a configuration containing a list of them.
extractValues :: LispConfig -> Result [LispConfig]
extractValues c = tail `fmap` fromLispConfig c

-- | Verify whether the given configuration has a certain name or not.fmap
-- The name of a configuration is its first parameter, if it is a string.
isNamed :: String -> LispConfig -> Bool
isNamed key (LCList (LCString x:_)) = x == key
isNamed _ _ = False

-- | Parser for recognising the current state of a Xen domain.
parseState :: String -> ActualState
parseState s =
  case s of
    "r-----" -> ActualRunning
    "-b----" -> ActualBlocked
    "--p---" -> ActualPaused
    "---s--" -> ActualShutdown
    "----c-" -> ActualCrashed
    "-----d" -> ActualDying
    _ -> ActualUnknown

-- | Extract the configuration data of a Xen domain from a generic LispConfig
-- data structure. Fail if the LispConfig does not represent a domain.
getDomainConfig :: LispConfig -> Result Domain
getDomainConfig configData = do
  domainConf <-
    if isNamed "domain" configData
      then extractValues configData
      else Bad $ "Not a domain configuration: " ++ show configData
  domid <- getValue "domid" domainConf
  name <- getValue "name" domainConf
  cpuTime <- getValue "cpu_time" domainConf
  state <- getValue "state" domainConf
  let actualState = parseState state
  return $ Domain domid name cpuTime actualState Nothing

-- | A parser for parsing the output of the @xm list --long@ command.
-- It adds the semantic layer on top of lispConfigParser.
-- It returns a map of domains, with their name as the key.
-- FIXME: This is efficient under the assumption that only a few fields of the
-- domain configuration are actually needed. If many of them are required, a
-- parser able to directly extract the domain config would actually be better.
xmListParser :: Parser (Map.Map String Domain)
xmListParser = do
  configs <- lispConfigParser `AC.manyTill` A.endOfInput
  let domains = map getDomainConfig configs
      foldResult m (Ok val) = Ok $ Map.insert (domName val) val m
      foldResult _ (Bad msg) = Bad msg
  case foldM foldResult Map.empty domains of
    Ok d -> return d
    Bad msg -> fail msg

-- | A parser for parsing the output of the @xm uptime@ command.
xmUptimeParser :: Parser (Map.Map Int UptimeInfo)
xmUptimeParser = do
  _ <- headerParser
  uptimes <- uptimeLineParser `AC.manyTill` A.endOfInput
  return $ Map.fromList [(uInfoID u, u) | u <- uptimes]
    where headerParser = A.string "Name" <* A.skipSpace <* A.string "ID"
            <* A.skipSpace <* A.string "Uptime" <* A.skipSpace

-- | A helper for parsing a single line of the @xm uptime@ output.
uptimeLineParser :: Parser UptimeInfo
uptimeLineParser = do
  name <- A.takeTill isSpace <* A.skipSpace
  idNum <- A.decimal <* A.skipSpace
  uptime <- A.takeTill (`elem` "\n\r") <* A.skipSpace
  return . UptimeInfo (unpack name) idNum $ unpack uptime
