import numpy as np
import typing
from typing import Any, List, Text, Optional, Dict, Type, Tuple

from rasa.engine.graph import ExecutionContext
from rasa.engine.storage.resource import Resource
from rasa.engine.storage.storage import ModelStorage
from rasa.nlu.config import RasaNLUModelConfig
from rasa.nlu.components import Component
from rasa.nlu.featurizers.featurizer import DenseFeaturizerGraphComponent
from rasa.shared.nlu.training_data.features import Features
from rasa.nlu.tokenizers.tokenizer import Token, Tokenizer
from rasa.nlu.utils.mitie_utils import MitieNLP
from rasa.shared.nlu.training_data.training_data import TrainingData
from rasa.shared.nlu.training_data.message import Message
from rasa.nlu.constants import (
    DENSE_FEATURIZABLE_ATTRIBUTES,
    FEATURIZER_CLASS_ALIAS,
    TOKENS_NAMES,
)
from rasa.shared.nlu.constants import FEATURE_TYPE_SENTENCE, FEATURE_TYPE_SEQUENCE
from rasa.utils.tensorflow.constants import MEAN_POOLING, POOLING
from rasa.nlu.featurizers.dense_featurizer._mitie_featurizer import MitieFeaturizer

if typing.TYPE_CHECKING:
    import mitie

# TODO: This is a workaround around until we have all components migrated to
# `GraphComponent`.
MitieFeaturizer = MitieFeaturizer


class MitieFeaturizerGraphComponent(DenseFeaturizerGraphComponent):
    @classmethod
    def create(
        cls,
        config: Dict[Text, Any],
        model_storage: ModelStorage,
        resource: Resource,
        execution_context: ExecutionContext,
        **kwargs: Any,
    ) -> GraphComponent:
        """Creates a new untrained policy (see parent class for full docstring)."""
        return cls(config, model_storage, resource, execution_context)

    @classmethod
    def load(
            cls,
            config: Dict[Text, Any],
            model_storage: ModelStorage,
            resource: Resource,
            execution_context: ExecutionContext,
            **kwargs: Any,
    ) -> MitieFeaturizerGraphComponent:
        pass

    def __init__(
        self,
        config: Optional[Dict[Text, Any]],
        model_storage: ModelStorage,
        resource: Resource,
        execution_context: ExecutionContext
    ) -> None:
        self.config = config

        self._model_storage = model_storage
        self._resource = resource

        self.pooling_operation = self.config["pooling"]

    @staticmethod
    def get_default_config() -> Dict[Text, Any]:
        return {
            # Specify what pooling operation should be used to calculate the vector of
            # the complete utterance. Available options: 'mean' and 'max'
            POOLING: MEAN_POOLING
        }

    @staticmethod
    def required_packages() -> List[Text]:
        """Any extra python dependencies required for this component to run."""
        return ["mitie", "numpy"]

    @classmethod
    def required_components(cls) -> List[Type[Component]]:
        return [MitieNLP, Tokenizer]

    def ndim(self, feature_extractor: "mitie.total_word_feature_extractor") -> int:
        return feature_extractor.num_dimensions

    def train(
        self,
        training_data: TrainingData,
        config: Optional[RasaNLUModelConfig] = None,
        **kwargs: Any,
    ) -> None:

        mitie_feature_extractor = self._mitie_feature_extractor(**kwargs)
        for example in training_data.training_examples:
            for attribute in DENSE_FEATURIZABLE_ATTRIBUTES:
                self.process_training_example(
                    example, attribute, mitie_feature_extractor
                )

    def process_training_example(
        self, example: Message, attribute: Text, mitie_feature_extractor: Any
    ) -> None:
        tokens = example.get(TOKENS_NAMES[attribute])

        if tokens is not None:
            sequence_features, sentence_features = self.features_for_tokens(
                tokens, mitie_feature_extractor
            )

            self._set_features(example, sequence_features, sentence_features, attribute)

    def process(self, message: Message, **kwargs: Any) -> None:
        mitie_feature_extractor = self._mitie_feature_extractor(**kwargs)
        for attribute in DENSE_FEATURIZABLE_ATTRIBUTES:
            tokens = message.get(TOKENS_NAMES[attribute])
            if tokens:
                sequence_features, sentence_features = self.features_for_tokens(
                    tokens, mitie_feature_extractor
                )

                self._set_features(
                    message, sequence_features, sentence_features, attribute
                )

    def _set_features(
        self,
        message: Message,
        sequence_features: np.ndarray,
        sentence_features: np.ndarray,
        attribute: Text,
    ) -> None:
        final_sequence_features = Features(
            sequence_features,
            FEATURE_TYPE_SEQUENCE,
            attribute,
            self.component_config[FEATURIZER_CLASS_ALIAS],
        )
        message.add_features(final_sequence_features)

        final_sentence_features = Features(
            sentence_features,
            FEATURE_TYPE_SENTENCE,
            attribute,
            self.component_config[FEATURIZER_CLASS_ALIAS],
        )
        message.add_features(final_sentence_features)

    def _mitie_feature_extractor(self, **kwargs: Any) -> Any:
        mitie_feature_extractor = kwargs.get("mitie_feature_extractor")
        if not mitie_feature_extractor:
            raise Exception(
                "Failed to train 'MitieFeaturizer'. "
                "Missing a proper MITIE feature extractor. "
                "Make sure this component is preceded by "
                "the 'MitieNLP' component in the pipeline "
                "configuration."
            )
        return mitie_feature_extractor

    def features_for_tokens(
        self,
        tokens: List[Token],
        feature_extractor: "mitie.total_word_feature_extractor",
    ) -> Tuple[np.ndarray, np.ndarray]:
        # calculate features
        sequence_features = []
        for token in tokens:
            sequence_features.append(feature_extractor.get_feature_vector(token.text))
        sequence_features = np.array(sequence_features)

        sentence_fetaures = self._calculate_sentence_features(
            sequence_features, self.pooling_operation
        )

        return sequence_features, sentence_fetaures
