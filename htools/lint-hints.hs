-- The following two hints warn to simplify e.g. "map (\v -> (v,
-- True)) lst" to "zip lst (repeat True)", which is more abstract
warn = map (\v -> (v, x)) y ==> zip y (repeat x)
  where _ = notIn v x
warn = map (\v -> (x, v)) ==> zip (repeat x)
  where _ = notIn v x
