// Expansion must preserve source data until actions have proved convergence.
// https://atlasgo.io/declarative/diff#diff-policy
env "expand" {
  diff {
    skip {
      drop_table  = true
      drop_column = true
      // A retained source column may still carry a foreign key to a retired
      // unique index. Defer standalone index drops with the source contraction.
      drop_index  = true
    }
  }
}
