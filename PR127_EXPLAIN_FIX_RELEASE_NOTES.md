# PR127 Explain Integration Fix — Release Notes

Default `atlas ai explain` repository responses now prioritize the PR127
Repository Summary Engine through a compact, source-free prompt. Detailed
symbols are omitted from the repository overview, while specific-subject
explanations remain backward compatible.

The fix also tightens PR128 architecture term matching to avoid classifying
`Support` names as ports.
