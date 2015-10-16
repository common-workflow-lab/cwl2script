import argparse
import cwltool.main
import sys
import os
import schema_salad
import logging
from cwltool.process import checkRequirements, shortname, adjustFiles
import shellescape
import re
import copy
import json

needs_shell_quoting = re.compile(r"""(^$|[\s|&;()<>\'"$@])""").search
glob_metacharacters = re.compile(r"""[\[\]\*?]""").search

def maybe_quote(arg):
    return shellescape.quote(arg) if needs_shell_quoting(arg) else arg

def generateScriptForTool(tool, job, outdir):
    for j in tool.job(job, "", None, outdir=outdir):
        return ("""mkdir -p %s  # output directory
mkdir -p %s  # temporary directory
%s%s%s
rm -r %s     # clean up temporary directory
""" % (maybe_quote(j.outdir), maybe_quote(j.tmpdir),
                                        " ".join([maybe_quote(arg) for arg in (j.command_line)]),
                           ' < %s' % maybe_quote(j.stdin) if j.stdin else '',
                                         ' > %s' % maybe_quote(os.path.join(j.outdir, j.stdout)) if j.stdout else '',
       maybe_quote(j.tmpdir)),
                j.outdir, j.tmpdir)


def generateScriptForWorkflow(cwlwf, cwljob, outdir):
    promises = {}
    jobs = {}
    script = ["#!/bin/sh",
              "",
              "# Workflow generated from %s using cwl2script" % (cwlwf.tool["id"]),
              ""
              "set -x",
              ""
          ]

    outdirs = []

    for inp in cwlwf.tool["inputs"]:
        promises[inp["id"]] = (cwlwf, cwljob[shortname(inp["id"])])

    alloutputs_fufilled = False
    while not alloutputs_fufilled:
        # Iteratively go over the workflow steps, adding jobs to the script as their
        # dependencies are fufilled by upstream workflow inputs or
        # step outputs.  Loop exits when the workflow outputs
        # are satisfied.

        alloutputs_fufilled = True

        progress = False
        for step in cwlwf.steps:
            if step.tool["id"] not in jobs:
                stepinputs_fufilled = True
                for inp in step.tool["inputs"]:
                    if "source" in inp and inp["source"] not in promises:
                        stepinputs_fufilled = False
                if stepinputs_fufilled:
                    jobobj = {}

                    # TODO: Handle multiple inbound links
                    # TODO: Handle scatter/gather
                    # (both are discussed in section 5.1.2 in CWL spec draft-2)

                    script.append("# Run step %s" % step.tool["id"])

                    for inp in step.tool["inputs"]:
                        if "source" in inp:
                            jobobj[shortname(inp["id"])] = promises[inp["source"]][1]
                            script.append("# depends on step %s" % promises[inp["source"]][0].tool["id"])
                        elif "default" in inp:
                            d = copy.copy(inp["default"])
                            jobobj[shortname(inp["id"])] = d

                    (wfjob, joboutdir, jobtmpdir) = generateScriptForTool(step.embedded_tool, jobobj, None)
                    outdirs.append(joboutdir)

                    jobs[step.tool["id"]] = True

                    script.append(wfjob)

                    for out in step.tool["outputs"]:
                        for toolout in step.embedded_tool.tool["outputs"]:
                            if shortname(toolout["id"]) == shortname(out["id"]):
                                if toolout["type"] != "File":
                                    raise Exception("Only supports file outputs")
                                if glob_metacharacters(toolout["outputBinding"]["glob"]):
                                    raise Exception("Only support glob with concrete filename.")
                                promises[out["id"]] = (step, {"class":"File", "path": os.path.join(joboutdir, toolout["outputBinding"]["glob"])})
                    progress = True

        for out in cwlwf.tool["outputs"]:
            if "source" in out:
                if out["source"] not in promises:
                    alloutputs_fufilled = False

        if not alloutputs_fufilled and not progress:
            raise Exception("Not making progress")

    outobj = {}
    script.append("# Move output files to the current directory")

    for out in cwlwf.tool["outputs"]:
        f = promises[out["source"]][1]
        script.append("mv %s ." % (maybe_quote(f["path"])))
        f["path"] = os.path.basename(f["path"])

        if f.get("secondaryFiles"):
            script.append("mv %s ." % (' '.join([maybe_quote(sf["path"]) for sf in f["secondaryFiles"]])))
            for sf in f["secondaryFiles"]:
                sf["path"] = os.path.basename(sf["path"])

        outobj[shortname(out["id"])] = f

    script.append("")
    script.append("# Clean up staging output directories")
    script.append("rm -r %s" % (' '.join([maybe_quote(od) for od in outdirs])))
    script.append("")

    script.append("# Generate final output object")
    script.append("echo '%s'" % json.dumps(outobj, indent=4))

    return "\n".join(script)



supportedProcessRequirements = ["SchemaDefRequirement"]

def main(args=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("cwltool", type=str)
    parser.add_argument("cwljob", type=str)

    parser.add_argument("--conformance-test", action="store_true")
    parser.add_argument("--no-container", action="store_true")
    parser.add_argument("--basedir", type=str)
    parser.add_argument("--outdir", type=str, default=os.getcwd())

    options = parser.parse_args(args)

    uri = "file://" + os.path.abspath(options.cwljob)

    if options.conformance_test:
        loader = schema_salad.ref_resolver.Loader({})
    else:
        loader = schema_salad.ref_resolver.Loader({
            "@base": uri,
            "path": {
                "@type": "@id"
            }
        })

    job, _ = loader.resolve_ref(uri)

    t = cwltool.main.load_tool(options.cwltool, False, False, cwltool.workflow.defaultMakeTool, True)

    if type(t) == int:
        return t

    try:
        checkRequirements(t.tool, supportedProcessRequirements)
    except Exception as e:
        logging.error(e)
        return 33

    for inp in t.tool["inputs"]:
        if shortname(inp["id"]) in job:
            pass
        elif shortname(inp["id"]) not in job and "default" in inp:
            job[shortname(inp["id"])] = copy.copy(inp["default"])
        elif shortname(inp["id"]) not in job and inp["type"][0] == "null":
            pass
        else:
            raise Exception("Missing inputs `%s`" % shortname(inp["id"]))

    if options.conformance_test:
        sys.stdout.write(json.dumps(cwltool.main.single_job_executor(t, job, options.basedir, options, conformance_test=True), indent=4))
        return 0

    if not options.basedir:
        options.basedir = os.path.dirname(os.path.abspath(options.cwljob))

    outdir = options.outdir

    if t.tool["class"] == "Workflow":
        print generateScriptForWorkflow(t, job, outdir)
    elif t.tool["class"] == "CommandLineTool":
        print generateScriptForTool(t, job, outdir)

    return 0

if __name__=="__main__":
    sys.exit(main(sys.argv[1:]))
