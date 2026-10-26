// Prepare a PlayStation 1 memory image for analysis (run as a Ghidra -preScript).
//
// Ghidra has already imported the flat memory image (see decomp/image.py) as
// MIPS little-endian at its load address. Before auto-analysis runs, this
// script adds what the console provides around it:
//   * the rest of the 2 MB main RAM, scratchpad, hardware I/O, BIOS ROM
//     (as uninitialised blocks, so references to them resolve)
//   * names and comments for the hardware registers (GPU_GP0, DMA2_GPU_CHCR, ...)
//   * optionally, a user-supplied copy of the Net Yaroze resident library
//     ("file" lines) and names for its entry points ("func" lines)
//   * the entry point, and the $gp register value that MIPS code uses to
//     reach its small-data area (without it, gp-relative loads stay anonymous)
//
// Arguments: <symbols.tsv> <entry hex> <gp hex or "-">
//@category PSX
import java.io.InputStream;
import java.math.BigInteger;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.List;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.lang.Register;
import ghidra.program.model.listing.ProgramContext;
import ghidra.program.model.mem.Memory;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.symbol.SourceType;

public class PsxSetup extends GhidraScript {

	@Override
	public void run() throws Exception {
		String[] args = getScriptArgs();
		if (args.length < 3) {
			printerr("usage: PsxSetup.java <symbols.tsv> <entry hex> <gp hex or ->");
			return;
		}
		List<String> lines = Files.readAllLines(Paths.get(args[0]));
		Memory mem = currentProgram.getMemory();

		// The imported image itself: code and data, readable, writable, executable.
		for (MemoryBlock b : mem.getBlocks()) {
			b.setRead(true);
			b.setWrite(true);
			b.setExecute(true);
		}

		int regions = 0, labels = 0, funcs = 0;
		for (String line : lines) {
			String[] f = line.split("\t");
			if (f.length >= 5 && f[0].equals("file")) {
				Address start = toAddr(Long.parseLong(f[2], 16));
				long size = Long.parseLong(f[3], 16);
				try (InputStream in = Files.newInputStream(Paths.get(f[4]))) {
					MemoryBlock b = mem.createInitializedBlock(f[1], start, in, size, monitor, false);
					b.setRead(true);
					b.setWrite(true);
					b.setExecute(true);
					b.setComment("user-supplied " + f[1]);
				}
				println("loaded " + f[1] + " at " + start);
			}
		}
		for (String line : lines) {
			String[] f = line.split("\t");
			if (f.length >= 5 && f[0].equals("region")) {
				Address start = toAddr(Long.parseLong(f[2], 16));
				long size = Long.parseLong(f[3], 16);
				if (mem.intersects(start, start.add(size - 1))) {
					println("skip region " + f[1] + ": overlaps loaded data");
					continue;
				}
				MemoryBlock b = mem.createUninitializedBlock(f[1], start, size, false);
				String kind = f[4];
				b.setRead(true);
				b.setWrite(!kind.equals("rom"));
				b.setExecute(kind.equals("ram") || kind.equals("rom"));
				b.setVolatile(kind.equals("io"));
				b.setComment("PS1 " + kind);
				regions++;
			}
		}
		for (String line : lines) {
			String[] f = line.split("\t");
			if (f.length >= 4 && f[0].equals("label")) {
				Address a = toAddr(Long.parseLong(f[2], 16));
				if (mem.contains(a)) {
					createLabel(a, f[1], true, SourceType.IMPORTED);
					setEOLComment(a, f[3]);
					labels++;
				}
			}
		}

		for (String line : lines) {
			String[] f = line.split("\t");
			if (f.length >= 4 && f[0].equals("func")) {
				Address a = toAddr(Long.parseLong(f[2], 16));
				if (!mem.contains(a)) continue;
				createLabel(a, f[1], true, SourceType.IMPORTED);
				MemoryBlock b = mem.getBlock(a);
				if (b != null && b.isInitialized()) {
					disassemble(a);
					if (getFunctionAt(a) == null) createFunction(a, f[1]);
				}
				funcs++;
			}
		}

		Address entry = toAddr(Long.parseLong(args[1], 16));
		addEntryPoint(entry);
		createLabel(entry, "entry", true, SourceType.IMPORTED);
		disassemble(entry);

		if (!args[2].equals("-")) {
			long gpValue = Long.parseLong(args[2], 16);
			Register gp = currentProgram.getRegister("gp");
			ProgramContext ctx = currentProgram.getProgramContext();
			for (MemoryBlock b : mem.getBlocks()) {
				if (b.isExecute()) {
					ctx.setValue(gp, b.getStart(), b.getEnd(), BigInteger.valueOf(gpValue));
				}
			}
			println(String.format("gp = 0x%08X", gpValue));
		}
		println(String.format("PsxSetup: %d regions, %d labels, %d library names, entry 0x%s", regions, labels, funcs, args[1]));
	}
}
