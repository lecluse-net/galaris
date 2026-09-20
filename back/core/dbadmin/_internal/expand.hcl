// Expansion must preserve source data until actions have proved convergence.
// https://atlasgo.io/declarative/diff#diff-policy
env "expand" {
  diff {
    skip {
      drop_table  = true
      drop_column = true
    }
  }
}
