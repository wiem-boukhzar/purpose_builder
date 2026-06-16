# SHACL vs. Pre-Computed Child Map Validation

This note contrasts two approaches the Purpose Creator agent uses (or can use) to flag “generic” Disease Ontology concepts, and explains why the original SHACL path is comparatively slow.

---

## 1. Goal

Detect when a user-selected disease term is an umbrella concept that still needs a more specific subtype. In both implementations, the rule is effectively:

> If an ontology class has at least one subclass, prompt the user to pick a more specific child.

---

## 2. SHACL-Based Validation

**Code path**: `purpose_app/common.py → ontology_validation/validator.py`.

### Mechanics
1. Build a temporary RDF “data graph” with a single node `:intent`, type `ex:ResearchIntent`, and one `ex:diseaseConcept` triple per linked disease.
2. Load the SHACL shapes graph (`ontology_validation/shapes.ttl`) containing:
   ```turtle
   ex:ResearchIntentShape      # ensures at least one disease
   ex:DiseaseSpecificityShape  # SPARQL constraint: ?child rdfs:subClassOf $this
   ```
3. Call `pyshacl.validate` with RDFS inference enabled.
4. Parse the resulting RDF report to enumerate violating IRIs and produce user-facing messages/suggestions.

### Why it’s slow
`pyshacl.validate` is heavy-weight:
- It parses and materialises the data graph, shapes graph, and (optionally) the ontology graph.
- The engine performs RDFS closure (inference) to respect subclass/equivalent-class semantics.
- It executes the SPARQL constraint over the combined model.
- It builds a detailed SHACL results graph (with `sh:ValidationResult` nodes, messages, severities, etc.).

These steps are repeated every time we call `validate_diseases`, unless we cache the result. The full Disease Ontology graph (~26 MB) makes the inference and SPARQL phases particularly expensive.

### Strengths
- Declarative, extensible: new SHACL rules can be added without revisiting application code.
- Standardised results: report graphs are easy to audit/share.
- Leverages inference: if the ontology adds OWL/RDFS relationships, the engine respects them.
- Future-proof: additional cardinality or datatype rules can be layered in the same shapes file.

### Weaknesses
- Runtime cost (latency + CPU) even for simple rules.
- Larger dependency footprint (`pyshacl`, `rdflib` SPARQL extras).
- More complex to debug; constrained by SHACL semantics.

---

## 3. Pre-Computed Child Map (Interactive Heuristic)

### Mechanics
1. During ontology load (`ontology_validation/ontology_loader.build_child_map`), walk all `rdfs:subClassOf` edges once and record which IRIs have direct subclasses. A companion `CHILDREN_INDEX` caches the actual child IRIs.
2. When validating diseases mid-conversation, look up `HAS_CHILDREN[iri]`.
3. If `True`, surface subtype suggestions via the cached index (with a SPARQL fallback) and block completion until the user picks a more specific term.
4. Skip SHACL during normal chat turns to keep latency low; defer the full report to the final validation step.

### Performance characteristics
- After the initial ontology load, the generic check is effectively a Python dictionary lookup, so validation is near-instant.
- The suggestion step reuses cached children, only hitting SPARQL if the cache misses.

### Strengths
- Extremely fast — ideal for interactive chat flows.
- Minimal runtime overhead (no SHACL dependency on each turn).
- Easy to reason about, easy to log and profile.

### Weaknesses
- Less expressive: limited to “has direct child” unless more custom code is added.
- No standard report output; all messaging is bespoke.
- Must manually account for inference rules (e.g. transitive subclasses) if needed.
- Adding new validation rules requires application logic changes.

---

## 4. Recommendation

| Scenario | Prefer SHACL | Prefer Pre-Computed |
| --- | --- | --- |
| Need multiple complex validation rules (cardinality, datatypes, cross-field constraints) | ✅ | |
| Desire industry-standard, auditable constraint definitions | ✅ | |
| Runtime latency is critical (e.g., conversational UX) | | ✅ |
| Only care about “has subclasses” and similar simple checks | | ✅ |
| Expect ontology/schema to evolve, handled by ontology team | ✅ | |

Many teams start with SHACL for correctness and future-proofing, then introduce caching (already in place) or hybrid schemes: run SHACL offline/periodically, use the pre-computed map for interactive flows, and keep SHACL for regression testing or nightly validation.

---

## 5. Files Referenced

- `docs/ARCHITECTURE.md`, `docs/AGENT_OVERVIEW.md`
- `ontology_validation/ontology_loader.py`
- `ontology_validation/disease_linker.py`
- `ontology_validation/validator.py`
- `ontology_validation/suggestions.py`
- `ontology_validation/shapes.ttl`
