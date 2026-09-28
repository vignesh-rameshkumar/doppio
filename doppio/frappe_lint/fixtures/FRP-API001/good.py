import click
import frappe


@frappe.whitelist(methods=["GET"])
def methods_declared():
    return "ok"


@click.command()
def unrelated_zero_arg_decorator_is_not_frappe_whitelist():
    # any other zero-arg decorator call looks structurally identical to
    # @frappe.whitelist() -- must not be flagged just for the shape.
    pass
