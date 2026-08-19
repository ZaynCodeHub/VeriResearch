from veriresearch.graph import build_graph, initial_state, run


def test_full_graph_compiles():
    graph = build_graph(mode="full")
    node_names = set(graph.get_graph().nodes.keys())
    assert {"planner", "researcher", "writer", "verifier", "revise", "finalize"} <= node_names


def test_baseline_graph_compiles_without_revise_node():
    graph = build_graph(mode="baseline")
    node_names = set(graph.get_graph().nodes.keys())
    assert {"planner", "researcher", "writer", "verifier", "finalize"} <= node_names
    assert "revise" not in node_names


def test_initial_state_shape():
    state = initial_state("a test topic", mode="full")
    assert state["topic"] == "a test topic"
    assert state["mode"] == "full"
    assert state["sources"] == {}
    assert state["claims"] == {}
    assert state["revision_count"] == 0


def test_full_run_end_to_end_offline():
    """No API keys in the test environment: this exercises the deterministic
    planner, the offline researcher fallback, the deterministic writer, the
    heuristic judge, and the revise/finalize conditional edge, all hermetically."""
    result = run("a test topic with no offline corpus match", mode="full")
    assert result["report"] is not None
    assert "supported_rate" in result["verification_summary"]
    assert result["revision_count"] <= result["max_revisions"]


def test_baseline_run_publishes_unfiltered():
    result = run("the James Webb Space Telescope", mode="baseline")
    assert result["report"].dropped_claim_ids == []
    assert result["revision_count"] == 0


def test_full_run_on_corpus_topic_drops_contradicted_claims():
    """The bundled local corpus + deterministic writer's negation-strip
    perturbation (see nodes/writer.py) guarantees at least one CONTRADICTED
    claim on the writer's first draft; mode="full" must not publish it.

    With the revision loop now feeding rejected-claim feedback back into the
    writer (see nodes/verifier_node.py::_build_revision_feedback), those
    CONTRADICTED claims get healed on the next pass rather than reproduced
    forever — so the *first* verifier pass, not the final state, is where the
    guaranteed catch is checked.
    """
    result = run("the James Webb Space Telescope", mode="full")
    verifier_passes = [t for t in result["trace"] if t["node"] == "verifier"]
    assert verifier_passes[0]["label_counts"]["CONTRADICTED"] > 0


def test_full_run_revision_loop_heals_rejected_claims():
    """The revision loop should do more than retry blindly: feeding the
    verifier's rejection reasons back into the writer should let a later pass
    fix the claims that were caught on the first one, converging before
    max_revisions and shipping nothing dropped."""
    result = run("the James Webb Space Telescope", mode="full")
    verifier_passes = [t for t in result["trace"] if t["node"] == "verifier"]
    assert len(verifier_passes) > 1
    assert verifier_passes[-1]["label_counts"]["CONTRADICTED"] == 0
    assert result["report"].dropped_claim_ids == []
    assert result["revision_count"] < result["max_revisions"]
