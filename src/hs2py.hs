{-# LANGUAGE TemplateHaskell #-}

{-| Haskell to Python opcode generation program.

-}

{-

Copyright (C) 2011, 2012, 2013 Google Inc.
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

import Ganeti.Hs2Py.GenOpCodes
import Ganeti.Hs2Py.ListConstants
import Ganeti.THH.PyRPC
import qualified Ganeti.WConfd.Core as WConfd
import qualified Ganeti.Metad.ConfigCore as Metad

import System.Environment (getArgs)
import System.Exit (exitFailure)
import System.IO (hPutStrLn, stderr)

main :: IO ()
main = do
  args <- getArgs
  case args of
    ["--opcodes"] -> putStrLn showPyClasses
    ["--constants"] -> putConstants
    ["--wconfd-rpc"] -> putStrLn $
      $( genPyUDSRpcStubStr "ClientRpcStub" "WCONFD_SOCKET"
                            WConfd.exportedFunctions )
    ["--metad-rpc"] -> putStrLn $
      $( genPyUDSRpcStubStr "ClientRpcStub" "METAD_SOCKET"
                            Metad.exportedFunctions )
    _ -> do
      hPutStrLn stderr "Usage: hs2py --opcodes\
                                  \| --constants\
                                  \| --wconfd-rpc"
      exitFailure
