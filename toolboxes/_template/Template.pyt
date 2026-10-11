# -*- coding: utf-8 -*-
"""Template Python toolbox for ArcGIS Pro.

Copy this folder to start a new toolbox. See the README for the steps.
"""

import arcpy


class Toolbox:
    def __init__(self):
        """Define the toolbox. The toolbox name is the name of the .pyt file."""
        self.label = "Template Toolbox"
        # Alias used to call tools from Python, e.g. arcpy.TemplateTool_template().
        # Letters and numbers only.
        self.alias = "template"

        # List of tool classes in this toolbox
        self.tools = [TemplateTool]


class TemplateTool:
    def __init__(self):
        """Define the tool. The tool name is the name of the class."""
        self.label = "Template Tool"
        self.description = "Copies the input features to a new feature class."
        self.category = None

    def getParameterInfo(self):
        """Define the tool parameters."""
        in_features = arcpy.Parameter(
            displayName="Input Features",
            name="in_features",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input",
        )

        out_features = arcpy.Parameter(
            displayName="Output Features",
            name="out_features",
            datatype="DEFeatureClass",
            parameterType="Required",
            direction="Output",
        )

        return [in_features, out_features]

    def isLicensed(self):
        """Return False to prevent the tool from running, e.g. when a required
        extension is not available."""
        return True

    def updateParameters(self, parameters):
        """Modify parameter values and properties before internal validation.
        Called whenever a parameter is changed."""
        return

    def updateMessages(self, parameters):
        """Modify the messages created by internal validation for each parameter."""
        return

    def execute(self, parameters, messages):
        """Run the tool."""
        in_features = parameters[0].valueAsText
        out_features = parameters[1].valueAsText

        messages.addMessage(f"Copying {in_features} to {out_features}")
        arcpy.management.CopyFeatures(in_features, out_features)

    def postExecute(self, parameters):
        """Called after the outputs are processed and added to the display."""
        return
