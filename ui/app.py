"""PSX Decomp Studio web UI (Streamlit).

    cd ui && streamlit run app.py            # http://localhost:8501
    docker compose up ui                     # same, in a container

Each page lays out widgets and calls ui/logic.py, which does the work with the
ref/ tools. Set PSX_UI_PASSWORD to require a password (there is no default
login). The app reads uploads in memory and writes nothing to disk except a
temporary folder while linking an RSD set.
"""

from __future__ import annotations

import hmac
import os
import sys

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import logic  # noqa: E402

st.set_page_config(page_title="PSX Decomp Studio", page_icon="🎮", layout="wide")

PAGES = ["Library", "Look lab", "GTE jitter", "World generator", "File inspector", "Self-test"]


# ---------------------------------------------------------------- optional password

def _gate() -> bool:
    password = os.environ.get("PSX_UI_PASSWORD", "")
    if not password or st.session_state.get("auth"):
        return True
    with st.form("login"):
        st.title("PSX Decomp Studio")
        entered = st.text_input("Password", type="password")
        if st.form_submit_button("Enter"):
            if hmac.compare_digest(entered.encode(), password.encode()):
                st.session_state.auth = True
                st.rerun()
            st.error("Wrong password")
    return False


if not _gate():
    st.stop()

with st.sidebar:
    st.title("PSX Decomp Studio")
    st.caption("PlayStation 1 reference library and tools")
    page = st.radio("Page", PAGES, label_visibility="collapsed")
    st.divider()
    st.caption("Renders are simulations of PS1 rules (`ref/tools/raster.py`), not hardware captures.")


def look_controls(prefix: str, default: logic.LookSettings) -> logic.LookSettings:
    return logic.LookSettings(
        integer_vertices=st.checkbox("Integer vertices (GTE jitter)", default.integer_vertices, key=prefix + "iv"),
        affine=st.checkbox("Affine texture mapping", default.affine, key=prefix + "af"),
        dither=st.checkbox("15-bit + 4×4 dither", default.dither, key=prefix + "di"),
        ordering_table=st.checkbox("Ordering table (no Z-buffer)", default.ordering_table, key=prefix + "ot"),
        fog=st.checkbox("Depth-cue fog", default.fog, key=prefix + "fo"),
    )


# ---------------------------------------------------------------- pages

def page_library() -> None:
    st.header("Library")
    query = st.text_input("Search titles, tags and summaries", placeholder="e.g. winding, fog, tmd, net yaroze")
    docs = logic.search_docs(query) if query else logic.list_docs()
    if not docs:
        st.info("No document matches.")
        return
    labels = {f"{d['title']}  ·  ref/{d['path']}": d for d in docs}
    choice = st.selectbox("Document", list(labels))
    doc = labels[choice]
    st.caption(doc["summary"] + "  ·  tags: " + ", ".join(doc["tags"]))
    images = logic.doc_images(doc["path"])
    if images:
        cols = st.columns(2)
        for i, (name, data) in enumerate(images):
            cols[i % 2].image(data, caption=name, use_container_width=True)
    st.markdown(logic.read_doc(doc["path"]))


def page_look_lab() -> None:
    st.header("Look lab")
    st.write("Render one scene twice, switching each PS1 hardware rule on or off, "
             "and compare. See `ref/look/visual-signature.md` for what each rule causes.")
    scene = st.selectbox("Scene", list(logic.SCENE_NAMES), format_func=logic.SCENE_NAMES.get)
    left, right = st.columns(2)
    with left:
        st.subheader("A: PS1 rules")
        a = look_controls("a", logic.LookSettings())
    with right:
        st.subheader("B: modern")
        b = look_controls("b", logic.LookSettings.modern())
    with st.spinner("Rendering (pure Python, about a second)…"):
        (png_a, sa), (png_b, sb) = logic.render_scene(scene, a), logic.render_scene(scene, b)
    left.image(png_a, use_container_width=True)
    left.caption(f"{sa['drawn_tris']} triangles drawn, {sa['culled_back']} back faces culled, {sa['dropped_near']} near-plane drops")
    right.image(png_b, use_container_width=True)
    right.caption(f"{sb['drawn_tris']} triangles drawn, {sb['culled_back']} back faces culled, {sb['dropped_near']} near-plane drops")
    st.subheader("Colour depth")
    c1, c2 = st.columns(2)
    c1.image(logic.render_gradient(True), caption="15-bit with the PS1 dither", use_container_width=True)
    c2.image(logic.render_gradient(False), caption="15-bit without dither (banding)", use_container_width=True)


def page_jitter() -> None:
    st.header("GTE jitter")
    st.write("A vertex slides sideways at a fixed depth. The GTE returns whole-pixel screen "
             "coordinates, so its position moves in steps while the true position moves smoothly.")
    depth = st.slider("Depth (SZ)", 200, 8000, 2000, 100)
    distance = st.slider("Distance moved (world units)", 5, 200, 30, 5)
    rows = logic.jitter_series(depth, distance)
    st.line_chart(rows, x="world_x", y=["float_screen_x", "gte_screen_x"])
    steps = len({r["gte_screen_x"] for r in rows})
    st.caption(f"{len(rows)} positions map to {steps} distinct screen pixels. "
               "Farther away (larger depth) means bigger, rarer jumps.")


def page_world() -> None:
    st.header("World generator")
    c1, c2, c3 = st.columns(3)
    kind = c1.selectbox("Kind", ["terrain", "dungeon"])
    seed = c2.number_input("Seed", 0, 1_000_000, 1)
    size = c3.slider("Grid size (cells)", 8, 48, 32 if kind == "terrain" else 24)
    with st.spinner("Generating and rendering…"):
        w = logic.generate_world(kind, int(seed), int(size))
    st.image(w.png, caption="PS1-style preview (baked vertex colour, depth cue, dither)")
    st.write(w.model_stats)
    if w.ascii_map:
        st.code(w.ascii_map, language=None)
    st.download_button("Download OBJ (with vertex colours)", w.obj, file_name=f"{kind}_{seed}.obj")
    st.caption("Algorithms: `ref/world/procedural-recipes.md`")


def page_inspector() -> None:
    st.header("File inspector")
    st.write("Upload PS1 files: a **TIM** texture, a **TMD** model, an executable (**PS-X EXE**, "
             "Net Yaroze **ECOFF**, Psy-Q **CPE**), or an **RSD** model set (select the .RSD with "
             "its .PLY, .MAT, .GRP and .TIM files together).")
    c1, c2 = st.columns(2)
    if c1.button("Try a sample TIM"):
        st.session_state.sample = ("sample.tim", logic.sample_tim())
    if c2.button("Try a sample TMD"):
        st.session_state.sample = ("house.tmd", logic.sample_tmd())
    uploads = st.file_uploader("Files", accept_multiple_files=True)
    files = {u.name: u.getvalue() for u in uploads} if uploads else {}
    if not files and "sample" in st.session_state:
        name, data = st.session_state.sample
        files = {name: data}
    if not files:
        return

    if any(n.lower().endswith(".rsd") for n in files):
        scale = st.select_slider("RSDLINK scale (-s)", [1, 2, 4, 8, 16, 32, 64], 1)
        try:
            info, tmd_bytes = logic.link_rsd(files, scale)
        except (ValueError, OSError, KeyError, IndexError) as e:
            st.error(f"Could not link: {e}")
            return
        st.success(info)
        st.download_button("Download linked TMD", tmd_bytes, file_name="linked.tmd")
        show_tmd("linked.tmd", tmd_bytes)
        return

    for name, data in files.items():
        st.subheader(name)
        kind = logic.detect_kind(name, data)
        try:
            if kind == "tim":
                clut = st.number_input("Palette (CLUT row)", 0, 255, 0, key="clut_" + name)
                info, png = logic.inspect_tim(data, int(clut))
                st.write(info)
                if png:
                    st.image(png)
            elif kind == "tmd":
                show_tmd(name, data)
            elif kind == "exe":
                text, header = logic.inspect_exe(data)
                st.write(text)
                st.json({k: (f"0x{v:08X}" if isinstance(v, int) and v > 0xFFFF else v)
                         for k, v in header.items() if k != "registers"})
            else:
                st.warning("Not recognised as TIM, TMD, RSD or a PS1 executable.")
        except ValueError as e:
            st.error(f"Rejected: {e}")


def show_tmd(name: str, data: bytes) -> None:
    info, obj = logic.inspect_tmd(data)
    c1, c2 = st.columns([2, 1])
    with c2:
        st.code(info, language=None)
        yaw = st.slider("Turn", -180, 180, 30, 5, key="yaw_" + name)
        pitch = st.slider("Tilt", -60, 80, 20, 5, key="pitch_" + name)
        ps1 = st.toggle("PS1 rules", True, key="ps1_" + name)
        st.download_button("Download OBJ", obj, file_name=os.path.splitext(name)[0] + ".obj", key="obj_" + name)
    settings = logic.LookSettings() if ps1 else logic.LookSettings.modern()
    png, stats = logic.render_tmd(data, yaw, pitch, settings)
    c1.image(png, use_container_width=True)
    c1.caption("Textures are not loaded (a TMD names VRAM positions, not files), so textured faces show grey. "
               f"{stats['drawn_tris']} triangles drawn.")


def page_selftest() -> None:
    st.header("Self-test")
    st.write("Runs the `ref/` test suite: the tools, Sony-manual packet sizes, winding, the RSD "
             "linker, executable readers, and the library's index and link checks.")
    if st.button("Run tests"):
        with st.spinner("Running…"):
            ok, output = logic.run_self_tests()
        (st.success if ok else st.error)("All tests passed" if ok else "Some tests failed")
        st.code(output, language=None)


{"Library": page_library, "Look lab": page_look_lab, "GTE jitter": page_jitter,
 "World generator": page_world, "File inspector": page_inspector, "Self-test": page_selftest}[page]()
