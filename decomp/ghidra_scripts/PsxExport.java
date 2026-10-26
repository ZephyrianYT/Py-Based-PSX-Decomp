// Annotate GTE instructions and export decompiled C (run as a Ghidra -postScript).
//
// Stock Ghidra disassembles a GTE command as a bare "cop2 0x..." word. This
// script looks up the command number (low 6 bits) and adds a comment such as
// "GTE RTPT: rotate, translate, perspective-project V0..V2" before the
// instruction. Pre-comments are printed by the decompiler, so they appear in
// the C output as well as the listing. Then it decompiles every function and writes:
//   <out>/c/<address>_<name>.c   one file per function
//   <out>/all.c                  every function, in address order
//   <out>/functions.json         name, address, size, GTE commands used, status
// Functions whose code is not in the program (calls into the resident library
// when no copy of it was supplied) are listed as "external" and not decompiled.
//   <out>/summary.json           totals
//
// Arguments: <out dir> <symbols.tsv>
//@category PSX
import java.io.PrintWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.mem.MemoryBlock;

public class PsxExport extends GhidraScript {

	private static String json(String s) {
		StringBuilder b = new StringBuilder("\"");
		for (char c : s.toCharArray()) {
			if (c == '"' || c == '\\') b.append('\\').append(c);
			else if (c < 0x20) b.append(String.format("\\u%04x", (int) c));
			else b.append(c);
		}
		return b.append('"').toString();
	}

	@Override
	public void run() throws Exception {
		String[] args = getScriptArgs();
		if (args.length < 2) {
			printerr("usage: PsxExport.java <out dir> <symbols.tsv>");
			return;
		}
		Path out = Paths.get(args[0]);
		Files.createDirectories(out.resolve("c"));

		Map<Integer, String[]> gte = new HashMap<>();
		for (String line : Files.readAllLines(Paths.get(args[1]))) {
			String[] f = line.split("\t");
			if (f.length >= 4 && f[0].equals("gte")) {
				gte.put(Integer.parseInt(f[2], 16), new String[] { f[1], f[3] });
			}
		}

		// 1. GTE annotation: COP2 (opcode 0x12) with the CO bit (25) set is a command.
		Map<Address, String> gteAt = new HashMap<>();
		TreeMap<String, Integer> gteTotals = new TreeMap<>();
		InstructionIterator it = currentProgram.getListing().getInstructions(true);
		while (it.hasNext() && !monitor.isCancelled()) {
			Instruction ins = it.next();
			int w = currentProgram.getMemory().getInt(ins.getAddress());
			if ((w >>> 26) == 0x12 && ((w >>> 25) & 1) == 1) {
				String[] cmd = gte.get(w & 0x3F);
				if (cmd != null) {
					setPreComment(ins.getAddress(), "GTE " + cmd[0] + ": " + cmd[1]);
					gteAt.put(ins.getAddress(), cmd[0]);
					gteTotals.merge(cmd[0], 1, Integer::sum);
				}
			}
		}

		// 2. Decompile every function.
		DecompInterface ifc = new DecompInterface();
		ifc.openProgram(currentProgram);
		int ok = 0, failed = 0, external = 0;
		StringBuilder index = new StringBuilder("[\n");
		try (PrintWriter all = new PrintWriter(Files.newBufferedWriter(out.resolve("all.c"), StandardCharsets.UTF_8))) {
			all.println("/* Decompiled by Ghidra via decomp/ghidra_scripts/PsxExport.java. */");
			all.println("/* Machine-generated pseudo-C: a starting point for reading, not compilable source. */\n");
			boolean first = true;
			for (Function fn : currentProgram.getFunctionManager().getFunctions(true)) {
				if (monitor.isCancelled()) break;
				String addr = fn.getEntryPoint().toString();
				MemoryBlock blk = currentProgram.getMemory().getBlock(fn.getEntryPoint());
				if (blk == null || !blk.isInitialized()) {
					external++;
					index.append(first ? "" : ",\n").append("  {\"name\": ").append(json(fn.getName()))
						.append(", \"address\": ").append(json("0x" + addr))
						.append(", \"size\": 0, \"decompiled\": false, \"external\": true, \"gte\": {}}");
					first = false;
					continue;
				}
				DecompileResults r = ifc.decompileFunction(fn, 60, monitor);
				String c;
				boolean done = r != null && r.decompileCompleted() && r.getDecompiledFunction() != null;
				if (done) {
					c = r.getDecompiledFunction().getC();
					ok++;
				} else {
					c = "/* " + fn.getName() + " @ " + addr + ": decompilation failed: "
						+ (r == null ? "no result" : r.getErrorMessage()) + " */\n";
					failed++;
				}
				all.println("/* ---- " + fn.getName() + " @ " + addr + " ---- */");
				all.println(c);
				String safe = fn.getName().replaceAll("[^A-Za-z0-9_]", "_");
				Files.write(out.resolve("c").resolve(addr + "_" + safe + ".c"), c.getBytes(StandardCharsets.UTF_8));

				TreeMap<String, Integer> used = new TreeMap<>();
				for (Address a : gteAt.keySet()) {
					if (fn.getBody().contains(a)) used.merge(gteAt.get(a), 1, Integer::sum);
				}
				StringBuilder g = new StringBuilder("{");
				for (Map.Entry<String, Integer> e : used.entrySet()) {
					if (g.length() > 1) g.append(", ");
					g.append(json(e.getKey())).append(": ").append(e.getValue());
				}
				g.append("}");
				index.append(first ? "" : ",\n").append("  {\"name\": ").append(json(fn.getName()))
					.append(", \"address\": ").append(json("0x" + addr))
					.append(", \"size\": ").append(fn.getBody().getNumAddresses())
					.append(", \"decompiled\": ").append(done)
					.append(", \"external\": false")
					.append(", \"gte\": ").append(g).append("}");
				first = false;
			}
		}
		finally {
			ifc.dispose();
		}
		index.append("\n]\n");
		Files.write(out.resolve("functions.json"), index.toString().getBytes(StandardCharsets.UTF_8));

		StringBuilder totals = new StringBuilder("{");
		for (Map.Entry<String, Integer> e : gteTotals.entrySet()) {
			if (totals.length() > 1) totals.append(", ");
			totals.append(json(e.getKey())).append(": ").append(e.getValue());
		}
		totals.append("}");
		String summary = "{\"program\": " + json(currentProgram.getName())
			+ ", \"functions\": " + (ok + failed) + ", \"decompiled\": " + ok + ", \"failed\": " + failed
			+ ", \"external\": " + external
			+ ", \"gte_instructions\": " + gteAt.size() + ", \"gte_by_command\": " + totals + "}\n";
		Files.write(out.resolve("summary.json"), summary.getBytes(StandardCharsets.UTF_8));
		println("PsxExport: " + ok + " functions decompiled, " + failed + " failed, " + external
			+ " external, " + gteAt.size() + " GTE instructions annotated");
	}
}
