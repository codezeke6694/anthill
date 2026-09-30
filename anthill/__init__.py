"""Anthill — a development agent system.

Three planes, one authority each, and none of them a model's opinion:

    navigate/    the blueprint    a structural fingerprint, so an agent cannot
                                  claim an address that is not there
    knowledge/   the intent       a human attestation, so it cannot claim intent
    orchestrate/ the foreman      a gate's exit code, so it cannot claim done

`sprint/` is the human-facing plane: work is discussed, planned, and reported
there. `gates/` holds the conditions a unit must satisfy to close.
"""
__version__ = "0.1.0"
