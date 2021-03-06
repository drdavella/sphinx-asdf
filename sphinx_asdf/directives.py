import posixpath
from pprint import pformat

import yaml

from docutils import nodes
from docutils.statemachine import ViewList

from sphinx import addnodes
from sphinx.util.nodes import nested_parse_with_titles
from sphinx.util.docutils import SphinxDirective

from .md2rst import md2rst
from .nodes import (toc_link, schema_header_title, schema_title,
                    schema_description, schema_properties, schema_property,
                    schema_property_name, schema_property_details,
                    schema_combiner_body, schema_combiner_list,
                    schema_combiner_item, section_header, asdf_tree, asdf_ref,
                    example_section, example_item, example_description)


SCHEMA_DEF_SECTION_TITLE = 'Schema Definitions'
EXAMPLE_SECTION_TITLE = 'Examples'
INTERNAL_DEFINITIONS_SECTION_TITLE = 'Internal Definitions'
ORIGINAL_SCHEMA_SECTION_TITLE = 'Original Schema'


class schema_def(nodes.comment):
    pass


class AsdfAutoschemas(SphinxDirective):

    required_arguments = 0
    optional_arguments = 0
    has_content = True

    def _process_asdf_toctree(self):

        standard_prefix = self.env.config.asdf_schema_standard_prefix

        links = []
        for name in self.content:
            if not name:
                continue
            schema = self.env.path2doc(name.strip() + '.rst')
            link = posixpath.join('generated', standard_prefix, schema)
            links.append((schema, link))

        tocnode = addnodes.toctree()
        tocnode['includefiles'] = [x[1] for x in links]
        tocnode['entries'] = links
        tocnode['maxdepth'] = -1
        tocnode['glob'] = None

        return [tocnode]


    def run(self):

        # This is the case when we are actually using Sphinx to generate
        # documentation
        if not getattr(self.env, 'autoasdf_generate', False):
            return self._process_asdf_toctree()

        # This case allows us to use docutils to parse input documents during
        # the 'builder-inited' phase so that we can determine which new
        # document need to be created by 'autogenerate_schema_docs'. This seems
        # much cleaner than writing a custom parser to extract the schema
        # information.
        return [schema_def(text=c.strip().split()[0]) for c in self.content]


class AsdfSchema(SphinxDirective):

    has_content = True

    def run(self):

        config = self.state.document.settings.env.config
        self.schema_name = self.content[0]
        schema_dir = config.asdf_schema_path
        standard_prefix = config.asdf_schema_standard_prefix
        srcdir = self.state.document.settings.env.srcdir

        schema_file = posixpath.join(srcdir, schema_dir, standard_prefix,
                                     self.schema_name) + '.yaml'

        with open(schema_file) as ff:
            raw_content = ff.read()
            schema = yaml.safe_load(raw_content)

        title = self._parse_title(schema.get('title', ''), schema_file)

        docnodes = [title]

        description = schema.get('description', '')
        if description:
            docnodes.append(schema_header_title(text='Description'))
            docnodes.append(self._parse_description(description, schema_file))

        docnodes.append(schema_header_title(text='Outline'))
        docnodes.append(self._create_toc(schema))

        docnodes.append(section_header(text=SCHEMA_DEF_SECTION_TITLE))
        docnodes.append(self._process_properties(schema, top=True))

        examples = schema.get('examples', [])
        if examples:
            docnodes.append(section_header(text=EXAMPLE_SECTION_TITLE))
            docnodes.append(self._process_examples(examples, schema_file))

        if 'definitions' in schema:
            docnodes.append(section_header(text=INTERNAL_DEFINITIONS_SECTION_TITLE))
            for name in schema['definitions']:
                path = 'definitions-{}'.format(name)
                tree = schema['definitions'][name]
                required = schema.get('required', [])
                docnodes.append(self._create_property_node(name, tree,
                                                           name in required,
                                                           path=path))

        docnodes.append(section_header(text=ORIGINAL_SCHEMA_SECTION_TITLE))
        docnodes.append(nodes.literal_block(text=raw_content, language='yaml'))

        return docnodes

    def _create_toc(self, schema):
        toc = nodes.compound()
        toc.append(toc_link(text=SCHEMA_DEF_SECTION_TITLE))
        if 'examples' in schema:
            toc.append(toc_link(text=EXAMPLE_SECTION_TITLE))
        if 'definitions' in schema:
            toc.append(toc_link(text=INTERNAL_DEFINITIONS_SECTION_TITLE))
        toc.append(toc_link(text=ORIGINAL_SCHEMA_SECTION_TITLE))
        return toc

    def _markdown_to_nodes(self, text, filename):
        """
        This function is taken from the original schema conversion code written
        by Michael Droetboom.
        """
        rst = ViewList()
        for i, line in enumerate(md2rst(text).split('\n')):
            rst.append(line, filename, i+1)

        node = nodes.section()
        node.document = self.state.document

        nested_parse_with_titles(self.state, rst, node)

        return node.children

    def _parse_title(self, title, filename):
        nodes = self._markdown_to_nodes(title, filename)
        return schema_title(None, *nodes)

    def _parse_description(self, description, filename):
        nodes = self._markdown_to_nodes(description, filename)
        return schema_description(None, *nodes)

    def _create_reference(self, refname):

        if '#' in refname:
            schema_id, fragment = refname.split('#')
        else:
            schema_id = refname
            fragment = ''

        if schema_id:
            schema_id += '.html'
        if fragment:
            components = fragment.split('/')
            fragment = '#{}'.format('-'.join(components[1:]))
            refname = components[-1]

        if schema_id and fragment:
            refname = '{}#{}'.format(schema_id, refname)

        return refname, schema_id + fragment

    def _create_ref_node(self, ref):
        treenodes = asdf_tree()
        refname, href = self._create_reference(ref)
        treenodes.append(asdf_ref(text=refname, href=href))
        return treenodes

    def _create_enum_node(self, enum_values):
        enum_nodes = nodes.compound()
        enum_nodes.append(nodes.line(
            text='Only the following values are valid for this node:'))
        markdown = '\n'.join(['* **{}**'.format(val) for val in enum_values])
        enum_nodes.extend(self._markdown_to_nodes(markdown, ''))
        return enum_nodes

    def _create_array_items_node(self, items, path):
        path = self._append_to_path(path, 'items')
        for combiner in ['anyOf', 'allOf']:
            if combiner in items:
                return self._create_combiner(items, combiner, array=True,
                                             path=path)

        node_list = nodes.compound()
        node_list.append(nodes.line(
            text='Items in the array are restricted to the following types:'))
        node_list.append(self._process_properties(items, top=True, path=path))
        return node_list

    def _process_validation_keywords(self, schema, typename=None, path=''):
        node_list = []
        typename = typename or schema['type']

        if typename == 'string':
            if not ('minLength' in schema or 'maxLength' in schema):
                node_list.append(nodes.emphasis(text='No length restriction'))
            if schema.get('minLength', 0):
                text = 'Minimum length: {}'.format(schema['minLength'])
                node_list.append(nodes.line(text=text))
            if 'maxLength' in schema:
                text = 'Maximum length: {}'.format(schema['maxLength'])
                node_list.append(nodes.line(text=text))
            if 'pattern' in schema:
                node_list.append(nodes.line(text='Must match the following pattern:'))
                node_list.append(nodes.literal_block(text=schema['pattern'],
                                                     language='none'))

        elif typename == 'array':
            if not ('minItems' in schema or 'maxItems' in schema):
                node_list.append(nodes.emphasis(text='No length restriction'))
            if schema.get('minItems', 0):
                text = 'Minimum length: {}'.format(schema['minItems'])
                node_list.append(nodes.line(text=text))
            if 'maxItems' in schema:
                text = 'Maximum length: {}'.format(schema['maxItems'])
                node_list.append(nodes.line(text=text))

            if 'items' in schema:
                node_list.append(self._create_array_items_node(schema['items'],
                                                               path=path))

        # TODO: more numerical validation keywords
        elif typename in ['integer', 'number']:
            if 'minimum' in schema:
                text = 'Minimum value: {}'.format(schema['minimum'])
                node_list.append(nodes.line(text=text))
            if 'maximum' in schema:
                text = 'Maximum value: {}'.format(schema['maximum'])
                node_list.append(nodes.line(text=text))

        if 'enum' in schema:
            node_list.append(self._create_enum_node(schema['enum']))

        if 'default' in schema:
            if typename in ['string', 'integer', 'number']:
                if typename == 'string' and not schema['default']:
                    default = "''"
                else:
                    default = schema['default']
                text = 'Default value: {}'.format(default)
                node_list.append(nodes.line(text=text))
            else:
                default_node = nodes.compound()
                default_node.append(nodes.line(text='Default value:'))
                default_node.append(nodes.literal_block(text=pformat(schema['default']),
                                                        language='none'))
                node_list.append(default_node)

        return node_list

    def _process_top_type(self, schema, path=''):
        tree = nodes.compound()
        prop = nodes.compound()
        typename = schema['type']
        prop.append(schema_property_name(text=typename))
        prop.extend(self._process_validation_keywords(schema, path=path))
        tree.append(prop)
        return tree

    def _append_to_path(self, path, new):
        if not path:
            return str(new).lower()
        else:
            return '{}-{}'.format(path, new).lower()

    def _process_properties(self, schema, top=False, path=''):
        for combiner in ['anyOf', 'allOf']:
            if combiner in schema:
                return self._create_combiner(schema, combiner, top=top,
                                             path=path)

        if 'properties' in schema:
            treenodes = asdf_tree()
            required = schema.get('required', [])
            for key, node in schema['properties'].items():
                new_path = self._append_to_path(path, key)
                treenodes.append(self._create_property_node(key, node,
                                                            key in required,
                                                            path=new_path))
            comment = nodes.line(text='This type is an object with the following properties:')
            return schema_properties(None, *[comment, treenodes], id=path)
        elif 'type' in schema:
            details = self._process_top_type(schema, path=path)
            return schema_properties(None, details, id=path)
        elif '$ref' in schema:
            ref = self._create_ref_node(schema['$ref'])
            return schema_properties(None, *[ref], id=path)
        else:
            text = nodes.emphasis(text='This node has no type definition (unrestricted)')
            return schema_properties(None, text, id=path)

    def _create_combiner(self, items, combiner, array=False, top=False, path=''):
        if top or array:
            container_node = nodes.compound()
        else:
            combiner_path = self._append_to_path(path, 'combiner')
            container_node = schema_combiner_body(path=combiner_path)

        path = self._append_to_path(path, combiner)

        if array:
            text = 'Items in the array must be **{}** of the following types:'
        else:
            text = 'This node must validate against **{}** of the following:'
        text = text.format(combiner.replace('Of', ''))
        text_nodes = self._markdown_to_nodes(text, '')
        container_node.extend(text_nodes)

        combiner_list = schema_combiner_list()
        for i, tree in enumerate(items[combiner]):
            new_path = self._append_to_path(path, i)
            properties = self._process_properties(tree, path=new_path)
            combiner_list.append(schema_combiner_item(None, *[properties]))

        container_node.append(combiner_list)
        container_node['ids'] = [path]
        return schema_properties(None, *[container_node], id=path)

    def _create_property_node(self, name, tree, required, path=''):

        description = tree.get('description', '')

        if '$ref' in tree:
            typ, ref = self._create_reference(tree.get('$ref'))
        else:
            typ = tree.get('type', 'object')
            ref = None

        prop = schema_property(id=path)
        prop.append(schema_property_name(text=name))
        prop.append(schema_property_details(typ, required, ref))
        prop.append(self._parse_description(description, ''))
        if typ != 'object':
            prop.extend(self._process_validation_keywords(tree, typename=typ, path=path))
        else:
            prop.append(self._process_properties(tree, path=path))

        prop['ids'] = [path]
        return prop

    def _process_examples(self, tree, filename):
        examples = example_section(num=len(tree))
        for i, example in enumerate(tree):
            node = example_item()
            desc_text = self._markdown_to_nodes(example[0]+':', filename)
            description = example_description(None, *desc_text)
            node.append(description)
            node.append(nodes.literal_block(text=example[1], language='yaml'))
            examples.append(node)
        return examples
