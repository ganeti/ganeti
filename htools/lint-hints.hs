{- Custom hint lints for Ganeti.

Since passing --hint to hlint will override, not extend the built-in hints, we need to import the existing hints so that we get full coverage.

-}

import "hint" HLint.Default
import "hint" HLint.Dollar

-- The following two hints warn to simplify e.g. "map (\v -> (v,
-- True)) lst" to "zip lst (repeat True)", which is more abstract
warn = map (\v -> (v, x)) y ==> zip y (repeat x)
  where _ = notIn v x
warn = map (\v -> (x, v)) ==> zip (repeat x)
  where _ = notIn v x

-- The following warn on use of length instead of null
warn = length x > 0 ==> not (null x)
warn = length x /= 0 ==> not (null x)
warn = length x == 0 ==> null x
